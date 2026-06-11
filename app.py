import os
import sys
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from google import genai
from google.genai import types

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
client = genai.Client(api_key=GEMINI_API_KEY)

# ==========================================
# 狀態記憶體：記錄每位使用者的解題進度與上下文
# user_sessions = { "user_id": {"state": 0, "history": "..."} }
# ==========================================
user_sessions = {}

def get_ai_response(prompt):
    """將封裝好的階段指令發送給 LLM，設定較低的溫度以確保邏輯精準 (防幻覺)"""
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2) 
    )
    return response.text if response and response.text else "系統分析中斷，請重試。"

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_msg = event.message.text.strip()
    
    # 隨時允許使用者重置狀態，開啟新題目
    if user_msg == "重新開始":
        if user_id in user_sessions:
            del user_sessions[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已重置狀態！請輸入您想挑戰的新題目或新聞："))
        return

    # 初始化新使用者的狀態
    if user_id not in user_sessions:
        user_sessions[user_id] = {"state": 0, "history": ""}

    session = user_sessions[user_id]
    current_state = session["state"]
    reply_text = ""

    try:
        # ----------------------------------------------------
        # 狀態 0：接收新題目，產出【拆解】與【工具箱選擇題】
        # ----------------------------------------------------
        if current_state == 0:
            prompt = f"""
            你是一個嚴格的邏輯拆解器。請分析以下使用者提供的題目或文章：
            【題目】：{user_msg}
            
            請嚴格依照以下格式輸出，不要包含其他內容，絕對不能給出最終答案：
            1. 【分析與拆解】
            指出這題的核心考點，並條列出內文的「已知條件」與「要求目標」。
            
            2. 【尋找工具箱】
            設計一個選擇題 (選項 A 與 B)，給予兩個計算公式或觀念。其中一個必須是正確的，另一個是常見的錯誤直覺。
            結尾請說：「請回覆我 A 或 B 來選擇你的破題公式！」
            """
            reply_text = get_ai_response(prompt)
            session["history"] += f"題目：{user_msg}\nAI提問：{reply_text}\n"
            session["state"] = 1  # 推進至等待選擇階段

        # ----------------------------------------------------
        # 狀態 1：驗證選擇，產出【嘗試第一步】
        # ----------------------------------------------------
        elif current_state == 1:
            prompt = f"""
            回顧我們剛才的對話：{session['history']}
            現在使用者選擇了：【{user_msg}】
            
            請判斷他的選擇是否正確。
            * 如果【錯誤】：請在開頭寫上「[錯誤]」，溫和地解釋為什麼這個選項不對，並請他重新選擇。
            * 如果【正確】：請在開頭寫上「[正確]」，並以「3. 【嘗試第一步】」為標題，要求他將題目的數字代入公式並計算出結果。絕對不要幫他算出數字，請把計算留給他。
            """
            reply_text = get_ai_response(prompt)
            session["history"] += f"使用者回答：{user_msg}\nAI回覆：{reply_text}\n"
            
            # 利用程式碼解析 LLM 的狀態標籤，決定是否推進關卡
            if "[正確]" in reply_text:
                reply_text = reply_text.replace("[正確]", "").strip() # 清除標籤讓排版好看
                session["state"] = 2
            elif "[錯誤]" in reply_text:
                reply_text = reply_text.replace("[錯誤]", "").strip()

        # ----------------------------------------------------
        # 狀態 2：驗證計算結果，產出【觀念總結與陷阱題】
        # ----------------------------------------------------
        elif current_state == 2:
            prompt = f"""
            回顧對話：{session['history']}
            使用者算出的結果是：【{user_msg}】
            
            請驗證他的計算。
            * 如果算錯了：請在開頭寫「[錯誤]」，指出他的計算盲點或粗心的地方，請他重算。
            * 如果算對了：請在開頭寫「[正確]」，並以「4. 【觀念總結與驗證】」為標題解釋結論。接著出一個「💡 終點挑戰（舉一反三）」的陷阱題（微調原本題目的條件），要求他回答這個新問題。
            """
            reply_text = get_ai_response(prompt)
            session["history"] += f"使用者回答：{user_msg}\nAI回覆：{reply_text}\n"
            
            if "[正確]" in reply_text:
                reply_text = reply_text.replace("[正確]", "").strip()
                session["state"] = 3
            elif "[錯誤]" in reply_text:
                reply_text = reply_text.replace("[錯誤]", "").strip()

        # ----------------------------------------------------
        # 狀態 3：驗證陷阱題，結束流程
        # ----------------------------------------------------
        elif current_state == 3:
            prompt = f"""
            回顧對話：{session['history']}
            使用者對陷阱題的回答是：【{user_msg}】
            
            請根據現實數據與邏輯給予最終解答，解開文字陷阱。
            結尾請加上：「🎉 恭喜通關！輸入『重新開始』可以挑戰新題目。」
            """
            reply_text = get_ai_response(prompt)
            # 流程結束，自動將狀態鎖定，等待使用者手動輸入重新開始
            session["state"] = 4 

        elif current_state == 4:
            reply_text = "本次挑戰已結束！請輸入「重新開始」來重置系統並輸入新題目。"

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        reply_text = "系統分析遇到一點阻礙，請輸入「重新開始」重試一次。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    app.run()
