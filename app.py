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

def get_ai_response(prompt):
    try:
        # 設定較低溫度，讓整理出來的筆記邏輯一致、不發散
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1) 
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
    user_msg = event.message.text.strip()
    
    # 保留重置指令，給使用者一個明確的操作感
    if user_msg == "重新開始" or user_msg == "清空":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已準備好！請直接貼上你想整理的內容："))
        return

    try:
        prompt = f"""
        你是一位極度講求效率的專業筆記整理師。請整理以下原始內容：
        【原始內容】：{user_msg}
        
        核心要求：
        1. 絕對不能使用星號 (*) 或任何 Markdown 符號排版。
        2. 永遠直觀有力，拒絕任何詞藻華麗的表達或冗長的開場白。
        3. 如果使用者輸入的內容毫無意義（如純數字、無意義的亂碼、極短的狀聲詞），請只輸出 `[INVALID]`。
        4. 若內容有效，請嚴格依照以下格式進行結構化輸出：
        
        【核心摘要】
        用一句話精準總結這段內容的重點。
        
        【重點梳理】
        以條列式列出細節，請使用數字 (1. 2. 3.) 代替項目符號。文字必須精煉。
        
        【待辦與結論】
        （若原始內容有提到需要執行的事，才列出此項。若無則直接省略這區塊。）
        """
        
        raw_reply = get_ai_response(prompt)
        
        # 捕捉亂碼或 API 當機，給予俐落的防呆回覆
        if "[ERROR]" in raw_reply or "[INVALID]" in raw_reply:
            reply_text = "請給予正確的筆記內容。"
        else:
            # 整理成功，直接回傳結果
            reply_text = raw_reply

    except Exception as e:
        print(f"Main Loop Error: {e}", file=sys.stderr)
        reply_text = "請給予正確的筆記內容。"

    # 回傳給 LINE
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    app.run()
