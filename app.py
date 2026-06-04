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

# ==================== 核心 Prompt 設計 (純情境 B：解題提示) ====================
SYSTEM_INSTRUCTION = """
你是一位經驗豐富、充滿耐心的「解題提示 AI 教學助理」。
當學生詢問任何學科的題目時，你的目標是帶領學生釐清觀念、自主破題，絕對不能直接提供標準答案或完整程式碼。請嚴格執行以下四階段引導歷程：

1. 【診斷問題與拆解題目】：請學生用自己的話描述題目想求什麼，並指出題目給了哪些已知條件。
2. 【連結已知觀念】：提示相關的概念、公式、定理或邏輯架構，引導學生從大腦尋找工具箱，但不直接套用。
3. 【嘗試第一步】：鼓勵學生寫出初步的列式或邏輯。如果卡住，用反問引導他發現矛盾，每次回覆只推進一個步驟。
4. 【觀念總結與內化】：當學生得出正確答案後，要求他用一句話總結解題核心，並給出一個微調條件的類似觀念提問讓他舉一反三。

注意：用肯定、直觀的語言建立信心。如果學生索要答案，請溫和拒絕並給予更微小的提示。每次回覆保持精簡，字數不超過 150 字。
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
    
    # 預設回覆
    reply = "助理正在思考如何引導你，請稍等..."
    
    try:
        # 呼叫 Gemini-2.5-flash，載入解題引導指令
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.7
            )
        )
        
        # 安全檢查
        if response and response.text:
            reply = response.text
        else:
            # 修正 1：移除時事分析字眼，改回純粹的解題引導
            reply = "這題看起來很有挑戰性！先別急著要答案，你可以告訴我，題目目前給了你哪些已知線索嗎？"
            
    except Exception as e:
        print(f'Gemini error: {e}', file=sys.stderr)
        # 修正 2：移除台積電與魏董事長的硬編碼，改為通用的解題防錯防護
        reply = "助理的腦袋剛剛稍微卡住了一下！我們回到這題，你能試著列出你的第一步算式或想法讓我看看嗎？"
    
    # 【對話紀錄蒐集】
    log_record = f"[{timestamp}] [{user_id}] -> Q: {user_msg.replace('\n', ' ')[:50]}... | A: {reply.replace('\n', ' ')}"
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
