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
# 狀態記憶體：新增 last_ai_message 紀錄上一次的正確問題
# ==========================================
user_sessions = {}

def get_ai_response(prompt):
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

    # 初始化包含 last_ai_message
    if user_id not in user_sessions:
        user_sessions[user_id] = {"state": 0, "history": "", "last_ai_message": ""}

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
            2. 如果使用者輸入的不是題目，而是毫無意義的亂碼或離題內容，請只輸出 `[INVALID]`。
            3. 如果是正常題目，請列出「已知條件」與「要求目標」，並設計一個正確與一個陷阱選項的選擇題。
            結尾加上：「請回覆 A 或 B，選擇你的破題工具！」
            """
            raw_reply = get_ai_response(prompt)
            
            # 只要出錯或被判定無效，直接擋回
            if "[ERROR]" in raw_reply or "[INVALID]" in raw_reply:
                reply_text = "請給予正確的題目。"
            else:
                reply_text = raw_reply
                session["history"] += f"題目：{user_msg}\nAI提問：{reply_text}\n"
                session["last_ai_message"] = reply_text  # 記錄下來
                session["state"] = 1

        # ----------------------------------------------------
        # 狀態 1：驗證選擇
        # ----------------------------------------------------
        elif current_state == 1:
            prompt = f"""
            對話紀錄：{session['history']}
            使用者選擇了：【{user_msg}】
            
            【強制輸出格式】
            第一行必須是狀態碼：正確寫 [PASS]，錯誤寫 [FAIL]。如果使用者輸入完全無意義或離題的亂碼，寫 [INVALID]。
            第二行開始寫回覆（絕對不能使用星號 * 排版）。
            
            - 若 [FAIL]：一針見血點出為什麼行不通，請他重選。
            - 若 [PASS]：下一行加上標題「【嘗試第一步】」，請他代入數字計算。
            """
            raw_reply = get_ai_response(prompt)
            
            if "[PASS]" in raw_reply:
                reply_text = raw_reply.replace("[PASS]", "").strip()
                session["history"] += f"使用者回答：{user_msg}\nAI回覆：{reply_text}\n"
                session["last_ai_message"] = reply_text
                session["state"] = 2
            elif "[FAIL]" in raw_reply:
                reply_text = raw_reply.replace("[FAIL]", "").strip()
                session["history"] += f"使用者回答：{user_msg}\nAI回覆：{reply_text}\n"
                session["last_ai_message"] = reply_text
            else:
                # 包含 [ERROR]、[INVALID] 或 LLM 格式跑掉，觸發防呆並回扣上次的有效提問
                reply_text = f"請給予正確的回答。\n\n{session['last_ai_message']}"

        # ----------------------------------------------------
        # 狀態 2：驗證計算結果
        # ----------------------------------------------------
        elif current_state == 2:
            prompt = f"""
            對話紀錄：{session['history']}
            使用者算出的結果是：【{user_msg}】
            
            【強制輸出格式】
            第一行必須是狀態碼：正確寫 [PASS]，錯誤寫 [FAIL]。如果使用者輸入完全無意義或離題的亂碼，寫 [INVALID]。
            第二行開始寫回覆（絕對不能使用星號 * 排版）。
            
            - 若 [FAIL]：直接點出盲點，請他重算。
            - 若 [PASS]：下一行加上標題「【觀念總結與驗證】」，俐落總結關鍵。接著出一個「終點挑戰（舉一反三）」的微調陷阱題，請他接招。
            """
            raw_reply = get_ai_response(prompt)
            
            if "[PASS]" in raw_reply:
                reply_text = raw_reply.replace("[PASS]", "").strip()
                session["history"] += f"使用者回答：{user_msg}\nAI回覆：{reply_text}\n"
                session["last_ai_message"] = reply_text
                session["state"] = 3
            elif "[FAIL]" in raw_reply:
                reply_text = raw_reply.replace("[FAIL]", "").strip()
                session["history"] += f"使用者回答：{user_msg}\nAI回覆：{reply_text}\n"
                session["last_ai_message"] = reply_text
            else:
                reply_text = f"請給予正確的回答。\n\n{session['last_ai_message']}"

        # ----------------------------------------------------
        # 狀態 3：驗證陷阱題
        # ----------------------------------------------------
        elif current_state == 3:
            prompt = f"""
            對話紀錄：{session['history']}
            使用者對陷阱題的回答是：【{user_msg}】
            
            要求：
            1. 絕對不能使用星號 (*) 排版。
            2. 如果使用者回答完全無意義或離題，請只輸出 `[INVALID]`。
            3. 若合理，請給予最終解答，結尾加上：「恭喜通關！輸入『重新開始』來挑戰下一題。」
            """
            raw_reply = get_ai_response(prompt)
            
            if "[ERROR]" in raw_reply or "[INVALID]" in raw_reply:
                reply_text = f"請給予正確的回答。\n\n{session['last_ai_message']}"
            else:
                reply_text = raw_reply
                session["state"] = 4 

        elif current_state == 4:
            reply_text = "本次挑戰已結束！請輸入「重新開始」來重置系統並丟出新題目。"

    except Exception as e:
        print(f"Main Loop Error: {e}", file=sys.stderr)
        # 底層發生致命錯誤時的終極防線
        fallback_msg = session.get("last_ai_message", "")
        if current_state == 0:
            reply_text = "請給予正確的題目。"
        else:
            reply_text = f"請給予正確的回答。\n\n{fallback_msg}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    app.run()
