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

user_sessions = {}

def get_ai_response(prompt):
    """加入 try-except，發生異常時統一回傳 [ERROR] 標籤"""
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2) 
        )
        if response and response.text:
            return response.text.strip()
        else:
            return "[ERROR]"
    except Exception as e:
        print(f"API Error: {e}", file=sys.stderr)
        return "[ERROR]"

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
    
    if user_msg == "重新開始":
        if user_id in user_sessions:
            del user_sessions[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="狀態已重置。請丟出你想挑戰的新題目："))
        return

    if user_id not in user_sessions:
        user_sessions[user_id] = {"state": 0, "history": ""}

    session = user_sessions[user_id]
    current_state = session["state"]
    reply_text = ""

    try:
        # ----------------------------------------------------
        # 狀態 0：接收新題目
        # ----------------------------------------------------
        if current_state == 0:
            prompt = f"""
            你是一位講話直白、俐落的專業導師。分析以下題目：
            【題目】：{user_msg}
            
            核心要求：
            1. 絕對不能使用星號 (*) 或任何 Markdown 符號排版。
            2. 表達直觀有力，拒絕廢話。
            3. 絕對不准給出最終答案。
            
            【分析與拆解】
            列出「已知條件」與「要求目標」。
            
            【尋找工具箱】
            設計一個選擇題 (選項 A 與 B)，一個正確，一個是常見陷阱。
            結尾加上：「請回覆 A 或 B，選擇你的破題工具！」
            """
            raw_reply = get_ai_response(prompt)
            
            if "[ERROR]" in raw_reply:
                reply_text = "連線遇到一點亂流，但沒關係。\n請再傳送一次你的「題目」，我們重新拆解！"
            else:
                reply_text = raw_reply
                session["history"] += f"題目：{user_msg}\nAI提問：{reply_text}\n"
                session["state"] = 1

        # ----------------------------------------------------
        # 狀態 1：驗證選擇
        # ----------------------------------------------------
        elif current_state == 1:
            prompt = f"""
            對話紀錄：{session['history']}
            使用者選擇了：【{user_msg}】
            
            請判斷他的選擇是否正確。必須允許模糊比對（大小寫或語意接近即可）。
            
            【強制輸出格式】
            第一行必須且只能是狀態碼：正確寫 [PASS]，錯誤寫 [FAIL]。
            第二行開始寫你的回覆（絕對不能使用星號 * 排版）。
            
            - 若 [FAIL]：一針見血點出為什麼行不通，請他重選。
            - 若 [PASS]：下一行加上標題「【嘗試第一步】」，請他代入數字計算。
            """
            raw_reply = get_ai_response(prompt)
            
            if "[PASS]" in raw_reply:
                reply_text = raw_reply.replace("[PASS]", "").strip()
                session["history"] += f"使用者回答：{user_msg}\nAI回覆：{reply_text}\n"
                session["state"] = 2
            elif "[FAIL]" in raw_reply:
                reply_text = raw_reply.replace("[FAIL]", "").strip()
                session["history"] += f"使用者回答：{user_msg}\nAI回覆：{reply_text}\n"
            else:
                # 攔截 ERROR 或 AI 漏印標籤的狀況，提示進度還在
                reply_text = "伺服器剛剛恍神了，但你的解題進度都還在！\n請再輸入一次你剛剛選的「選項」，我們接續上一部。"

        # ----------------------------------------------------
        # 狀態 2：驗證計算結果
        # ----------------------------------------------------
        elif current_state == 2:
            prompt = f"""
            對話紀錄：{session['history']}
            使用者算出的結果是：【{user_msg}】
            
            請判斷計算是否正確。允許合理誤差或單位未標示。
            
            【強制輸出格式】
            第一行必須且只能是狀態碼：正確寫 [PASS]，錯誤寫 [FAIL]。
            第二行開始寫你的回覆（絕對不能使用星號 * 排版）。
            
            - 若 [FAIL]：直接點出盲點，請他重算。
            - 若 [PASS]：下一行加上標題「【觀念總結與驗證】」，俐落總結關鍵。接著出一個「終點挑戰（舉一反三）」的微調陷阱題，請他接招。
            """
            raw_reply = get_ai_response(prompt)
            
            if "[PASS]" in raw_reply:
                reply_text = raw_reply.replace("[PASS]", "").strip()
                session["history"] += f"使用者回答：{user_msg}\nAI回覆：{reply_text}\n"
                session["state"] = 3
            elif "[FAIL]" in raw_reply:
                reply_text = raw_reply.replace("[FAIL]", "").strip()
                session["history"] += f"使用者回答：{user_msg}\nAI回覆：{reply_text}\n"
            else:
                reply_text = "連線稍微卡住了，解題進度已保留！\n請再輸入一次你剛剛算出的「答案」，讓我驗證一下。"

        # ----------------------------------------------------
        # 狀態 3：驗證陷阱題
        # ----------------------------------------------------
        elif current_state == 3:
            prompt = f"""
            對話紀錄：{session['history']}
            使用者對陷阱題的回答是：【{user_msg}】
            
            請給予最終解答。邏輯要一針見血（絕對不能使用星號 * 排版）。
            結尾請加上：「恭喜通關！輸入『重新開始』來挑戰下一題。」
            """
            raw_reply = get_ai_response(prompt)
            
            if "[ERROR]" in raw_reply:
                reply_text = "就差最後一步了，系統剛好卡住！\n請再傳送一次你的「最終答案」，我們完成這題。"
            else:
                reply_text = raw_reply
                session["state"] = 4 

        elif current_state == 4:
            reply_text = "本次挑戰已結束！請輸入「重新開始」來重置系統並丟出新題目。"

    except Exception as e:
        print(f"Main Loop Error: {e}", file=sys.stderr)
        reply_text = "系統發生未預期錯誤，但進度已保存。請再傳送一次剛剛的對話內容！"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    app.run()
