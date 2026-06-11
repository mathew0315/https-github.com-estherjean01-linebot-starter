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
# ==========================================
user_sessions = {}

def get_ai_response(prompt):
    """將封裝好的階段指令發送給 LLM，設定較低的溫度以確保邏輯精準 (防幻覺)"""
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2) 
    )
    return response.text if response and response.text else "思考過程卡住了，請重試。"

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
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="狀態已重置。請丟出你想挑戰的新題目或新聞："))
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
            你是一位講話直白、俐落且具備引導能力的專業導師。請分析以下題目：
            【題目】：{user_msg}
            
            核心要求：
            1. 絕對不能使用星號 (*) 或任何 Markdown 符號排版，請純粹使用文字與換行。
            2. 表達直觀有力，不說廢話，拒絕詞藻華麗的描述。
            3. 絕對不准給出最終答案，請嚴格依照以下格式回覆：
            
            【分析與拆解】
            直接點出核心考點，用清晰的白話文列出「已知條件」與「要求目標」。
            
            【尋找工具箱】
            設計一個選擇題 (選項 A 與 B)，給出兩個計算公式或觀念。一個是正確的，另一個是常見的直覺陷阱。
            結尾請加上：「請回覆 A 或 B，選擇你的破題工具！」
            """
            reply_text = get_ai_response(prompt)
            session["history"] += f"題目：{user_msg}\nAI提問：{reply_text}\n"
            session["state"] = 1  # 推進至等待選擇階段

        # ----------------------------------------------------
        # 狀態 1：驗證選擇，產出【嘗試第一步】
        # ----------------------------------------------------
        elif current_state == 1:
            prompt = f"""
            回顧目前的對話：{session['history']}
            使用者選擇了：【{user_msg}】
            
            核心要求：
            1. 絕對不能使用星號 (*) 排版。
            2. 語氣自然、直觀有力，不囉嗦。
            
            請判斷選擇是否正確：
            - 若【錯誤】：開頭寫上「[錯誤]」，一針見血地點出為什麼這個選項行不通，請他重新選擇。
            - 若【正確】：開頭寫上「[正確]」，下一行以「【嘗試第一步】」為標題，請他將數字代入公式並算出結果。注意：絕對不要幫他算，把計算權交給他。
            """
            reply_text = get_ai_response(prompt)
            session["history"] += f"使用者回答：{user_msg}\nAI回覆：{reply_text}\n"
            
            if "[正確]" in reply_text:
                reply_text = reply_text.replace("[正確]", "").strip() 
                session["state"] = 2
            elif "[錯誤]" in reply_text:
                reply_text = reply_text.replace("[錯誤]", "").strip()

        # ----------------------------------------------------
        # 狀態 2：驗證計算結果，產出【觀念總結與陷阱題】
        # ----------------------------------------------------
        elif current_state == 2:
            prompt = f"""
            回顧目前的對話：{session['history']}
            使用者算出的結果是：【{user_msg}】
            
            核心要求：
            1. 絕對不能使用星號 (*) 排版。
            2. 表達直觀有力，直接切入重點。
            
            請驗證他的計算：
            - 若算錯：開頭寫「[錯誤]」，直接點出他的盲點或粗心的地方，請他重算。
            - 若算對：開頭寫「[正確]」，下一行以「【觀念總結與驗證】」為標題，用俐落的文字總結這題的關鍵。接著出一個「💡 終點挑戰（舉一反三）」的陷阱題（微調原題條件），請他接招。
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
            回顧目前的對話：{session['history']}
            使用者對陷阱題的回答是：【{user_msg}】
            
            核心要求：
            1. 絕對不能使用星號 (*) 排版。
            2. 解開陷阱的邏輯要一針見血，語氣要像人一樣直接肯定他的努力。
            
            請給予最終解答。
            結尾請加上：「🎉 恭喜通關！輸入『重新開始』來挑戰下一題。」
            """
            reply_text = get_ai_response(prompt)
            session["state"] = 4 

        elif current_state == 4:
            reply_text = "本次挑戰已結束！請輸入「重新開始」來重置系統並丟出新題目。"

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        reply_text = "系統剛剛恍神了，請輸入「重新開始」重試一次。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    app.run()
