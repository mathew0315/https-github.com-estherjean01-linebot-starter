import os
import sys
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from google import genai
from google.genai import types

app = Flask(__name__)

# ==================== 配置環境變數 ====================
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 初始化 Google GenAI 用戶端
client = genai.Client(api_key=GEMINI_API_KEY)

# ==================== 建立記憶體 ====================
# 【關鍵新增】用一個字典來儲存每位使用者的專屬對話記憶
user_sessions = {}

# ==================== 核心 Prompt 設計 ====================
SYSTEM_INSTRUCTION = """
你是一位專業的「解題提示 AI 教學助理」。請嚴格遵循以下「四階段引導」與使用者進行【多輪對話】。
⚠️ 核心鐵則：絕對不要一次把所有步驟講完！每次「只能進行一個階段」，結尾必須拋出問題並「等待使用者回答」，才能進入下一階段。絕對不給最終答案。

1. 【分析與拆解】：指出核心考點，幫使用者抓出「已知條件」與「要求目標」。問使用者準備好開始了嗎？
2. 【尋找工具箱】：給出選項（例如 A 或 B 公式）或提示，詢問使用者覺得該用哪一個。等待使用者回答 A 或 B。
3. 【嘗試第一步】：確認使用者選對後，請他們將數字代入公式計算，並回覆結果。等待使用者算出數字。
4. 【觀念總結與驗證】：驗證使用者的計算，最後給出一個微調條件的「終點挑戰（陷阱題）」，等使用者回答後再給予結業鼓勵。

語氣：直觀有力、充滿鼓勵。記住，你是在對話，不是在寫報告。
"""

# ==================== Webhook 進入點 ====================
@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# ==================== 訊息處理與紀錄蒐集 ====================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_msg = event.message.text
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 【關鍵修改：啟動對話記憶】
    # 如果這個使用者是第一次傳訊息，幫他開一個專屬的 Chat Session
    if user_id not in user_sessions:
        user_sessions[user_id] = client.chats.create(
            model='gemini-2.5-flash',
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.7
            )
        )
    
    # 取得該使用者的專屬聊天室（帶有歷史記憶）
    chat_session = user_sessions[user_id]
    
    try:
        # 使用 chat_session.send_message 來延續對話，而不是 generate_content
        response = chat_session.send_message(user_msg)
        
        if response and response.text:
            reply = response.text
        else:
            reply = "這題看起來很有挑戰性！你可以告訴我，題目目前給了你哪些已知線索嗎？"
            
    except Exception as e:
        print(f'Gemini error: {e}', file=sys.stderr)
        reply = "助理的腦袋剛剛稍微卡住了一下！我們回到這題，你能試著列出你的第一步算式或想法讓我看看嗎？"
    
    # 【對話紀錄蒐集】
    log_record = f"[{timestamp}] [{user_id}] -> Q: {user_msg.replace(chr(10), ' ')[:50]}... | A: {reply.replace(chr(10), ' ')}"
    print(log_record, file=sys.stdout)
    sys.stdout.flush()

    # 回傳 LINE 訊息
    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
    except Exception as line_err:
        print(f'LINE Send Error: {line_err}', file=sys.stderr)

if __name__ == "__main__":
    app.run()
