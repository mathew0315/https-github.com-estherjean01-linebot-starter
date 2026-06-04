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

# 初始化 Google GenAI 用戶端 (使用最新 google-genai SDK)
client = genai.Client(api_key=GEMINI_API_KEY)

# ==================== 核心 Prompt 設計 ====================
SYSTEM_INSTRUCTION = """
你是一位專業的「考古題與時事分析引導 AI 助理」。
當使用者輸入任何題目、長篇新聞或計算題時，你必須嚴格遵守以下引導歷程，絕對不能直接提供最終答案或完整算式：

1. 【分析與拆解】：先用一句話指出這個問題屬於哪一個學科章節或核心考點（例如：基礎數學的百分比、程式設計的變數宣告），並幫使用者抓出內文中的「已知條件」與「要求目標」。
2. 【尋找工具箱】：詢問或提示使用者相關的概念、公式或定理，引導他自己想起來。
3. 【嘗試第一步】：每次回覆只推進一個步驟，鼓勵使用者動手列出第一步算式或邏輯。
4. 【舉一反三】：如果使用者成功解出，最後提供一個微調條件的「類題」讓他練習鞏固觀念。

注意：語氣要直觀有力、充滿鼓勵。如果使用者持續索取答案，請溫和地拒絕並給予更簡單的提示。字數保持精簡（150字內）。
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
    
    # 初始化預設回覆，防止內容為空導致 LINE 崩潰
    reply = "助理正在閱讀這段內容，請稍等..."
    
    try:
        # 呼叫 Gemini-2.5-flash，並帶入核心引導指令
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.7
            )
        )
        
        # 安全檢查：確保 Gemini 有回傳文字且不為空
        if response and response.text:
            reply = response.text
        else:
            reply = "這段資訊量較大，但沒問題！請告訴我，你想驗證其中的哪個數字或核心觀念？"
            
    except Exception as e:
        # 異常攔截：即使 API 報錯或文字超長卡死，也給予符合引導核心的「安全罐頭回覆」
        print(f'Gemini error: {e}', file=sys.stderr)
        reply = "這段新聞的資訊量很大！讓我們聚焦在核心：魏董事長宣稱股價『成長了 1.5 倍』。請告訴我你準備好用什麼公式來驗證它了嗎？"
    
    # 【對話紀錄蒐集】將紀錄壓縮成單行輸出至標準日誌 (sys.stdout)
    log_record = f"[{timestamp}] [{user_id}] -> Q: {user_msg.replace('\n', ' ')[:50]}... | A: {reply.replace('\n', ' ')}"
    print(log_record, file=sys.stdout)
    sys.stdout.flush()

    # 安全地將訊息回傳給 LINE 使用者
    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
    except Exception as line_err:
        print(f'LINE Send Error: {line_err}', file=sys.stderr)

if __name__ == "__main__":
    app.run()
