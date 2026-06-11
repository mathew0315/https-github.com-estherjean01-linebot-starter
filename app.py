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
# 狀態記憶體：簡化為只區分「接收題目(0)」與「已解答待重置(1)」
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
    
    # 隨時允許使用者重置狀態
    if user_msg == "重新開始":
        if user_id in user_sessions:
            del user_sessions[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="狀態已重置。請丟出你想挑戰的新題目："))
        return

    # 初始化狀態
    if user_id not in user_sessions:
        user_sessions[user_id] = {"state": 0}

    session = user_sessions[user_id]
    current_state = session["state"]
    reply_text = ""

    try:
        # ----------------------------------------------------
        # 狀態 0：接收題目，直接給出分析與結果
        # ----------------------------------------------------
        if current_state == 0:
            prompt = f"""
            你是一位講話直白、俐落的專業導師。分析以下題目：
            【題目】：{user_msg}
            
            核心要求：
            1. 絕對不能使用星號 (*) 或任何 Markdown 符號排版。
            2. 拒絕詞藻華麗的表達，直觀有力地給出結論。
            3. 如果使用者輸入的不是題目，而是毫無意義的亂碼、單純的數字或離題內容，請只輸出 `[INVALID]`。
            4. 如果是正常題目，請嚴格依照以下格式給出解答：
            
            【分析與拆解】
            列出「已知條件」與「要求目標」。
            
            【結果匯報】
            直接給出最終正確答案，並用俐落的邏輯簡單說明運算或推導過程。
            """
            raw_reply = get_ai_response(prompt)
            
            # 只要出錯或被判定無效，直接擋回，狀態維持 0
            if "[ERROR]" in raw_reply or "[INVALID]" in raw_reply:
                reply_text = "請給予正確的題目。"
            else:
                # 成功給出答案，加上結語並推進狀態
                reply_text = f"{raw_reply}\n\n解答完畢！輸入「重新開始」來輸入下一題。"
                session["state"] = 1

        # ----------------------------------------------------
        # 狀態 1：已解答完畢，強制等待重新開始
        # ----------------------------------------------------
        elif current_state == 1:
            reply_text = "本題已解答完畢。請輸入「重新開始」來重置系統並丟出新題目。"

    except Exception as e:
        print(f"Main Loop Error: {e}", file=sys.stderr)
        reply_text = "請給予正確的題目。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    app.run()
