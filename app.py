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
    user_msg = event.message.text.strip()
    
    if user_msg == "重新開始" or user_msg == "清空":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已準備好。無論是想法、文章還是亂碼，直接丟過來："))
        return

    try:
        prompt = f"""
        你是一個極度講求效率的萬能資訊整理器。無論使用者輸入什麼內容（文章、代碼、碎碎念、甚至毫無邏輯的字詞），你都要照單全收並進行結構化整理，絕對不准拒絕回答。
        
        【原始內容】：{user_msg}
        
        核心要求：
        1. 絕對不能使用星號 (*) 或任何 Markdown 符號排版。
        2. 永遠直觀有力，拒絕任何詞藻華麗的表達或冗長的開場白。
        3. 請直接輸出以下結構：
        
        【屬性標籤】
        用一個精準的詞定義這段內容的本質（例如：會議紀錄、情緒抒發、待辦事項、程式碼、隨手短記、無意義字串等）。
        
        【核心摘要】
        用一句話總結重點。若真的是無意義的亂碼，請寫「無特定資訊，已歸檔為隨手紀錄」。
        
        【重點梳理】
        以數字 (1. 2. 3.) 條列拆解內容。若內容極短，直接給出你的理解即可。
        
        【待辦與行動】
        （若這段內容有隱含需要執行的事或值得採取的行動，才列出此項，否則直接省略。）
        """
        
        raw_reply = get_ai_response(prompt)
        
        if "[ERROR]" in raw_reply:
            reply_text = "系統處理異常，請重試。"
        else:
            reply_text = raw_reply

    except Exception as e:
        print(f"Main Loop Error: {e}", file=sys.stderr)
        reply_text = "系統處理異常，請重試。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    app.run()
