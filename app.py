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
    user_msg = event.message.text.strip()

    try:
        prompt = f"""
        任務：資訊結構化處理。
        輸入內容：{user_msg}
        
        強制規則：
        1. 絕對不准使用星號 (*) 排版。
        2. 絕對不准產生任何開場白、結語或對話感字句（如：好的、為您整理）。
        3. 輸出必須冷靜、客觀。
        4. 嚴格依照以下格式直接輸出：
        
        【屬性】
        (用一個詞定義內容，如：會議、待辦、隨記、程式碼、情緒宣洩)
        
        【摘要】
        (一句話精準總結)
        
        【梳理】
        1. (重點拆解)
        2. (重點拆解)
        (若無具體重點則寫：無)
        """
        
        response = client.models.generate_content(
            # 若持續報錯，請將 model 改為 'gemini-2.0-flash' 或 'gemini-1.5-flash'
            model='gemini-2.5-flash', 
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1) 
        )
        
        if response and response.text:
            reply_text = response.text.strip()
        else:
            reply_text = "處理失敗：API 未回傳資料。"

    except Exception as e:
        print(f"API Error: {e}", file=sys.stderr)
        reply_text = "處理失敗：API 連線或模型設定異常，請檢查伺服器後台。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    app.run()
