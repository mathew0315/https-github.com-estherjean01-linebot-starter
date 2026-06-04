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

# 從環境變數取得金鑰
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 初始化 Google GenAI 戶端
client = genai.Client(api_key=GEMINI_API_KEY)

# 設計整合情境 B 與 C 的蘇格拉底式引導提示詞
SYSTEM_INSTRUCTION = """
你是一位專業的「考古題分析與解題引導 AI 助理」。
當使用者輸入任何題目、考古題或計算題時，你必須嚴格遵守以下引導歷程，絕對不能直接提供最終答案或完整算式：

1. 【分析與拆解】：先用一句話指出這個題目屬於哪一個學科章節或核心考點，並幫使用者抓出題目中的「已知條件」與「要求目標」。
2. 【尋找工具箱】：詢問或提示使用者相關的概念、公式或定理，引導他自己想起來（例如：「回想一下，處理這種圖形時通常會用什麼定理？」）。
3. 【嘗試第一步】：每次回覆只推進一個步驟，鼓勵使用者動手列出第一步算式或邏輯，並說明如果有盲點或陷阱要注意什麼。
4. 【舉一反三】：如果使用者成功解出，最後提供一個微調條件的「類題」讓他練習鞏固觀念。

注意：語氣要直觀有力、充滿鼓勵。如果使用者持續索取答案，請溫和地拒絕並給予更簡單的提示。字數保持精簡（150字內）。
"""

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
    user_msg = event.message.text
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    try:
        # 使用最新的 google-genai SDK 呼叫 gemini-2.5-flash，並帶入 system_instruction
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.7
            )
        )
        reply = response.text
    except Exception as e:
        print(f'Gemini error: {e}', file=sys.stderr)
        reply = f'助理思考時發生錯誤：{str(e)}'
    
    # 【對話紀錄蒐集】將紀錄格式化輸出至標準輸出，供日後分析使用
    # 格式：[時間] [User_ID] -> 提問: xxx | 回應: ooo
    log_record = f"[{timestamp}] [{user_id}] -> Q: {user_msg.replace('\n', ' ')} | A: {reply.replace('\n', ' ')}"
    print(log_record, file=sys.stdout)
    sys.stdout.flush()

    # 回傳訊息給 LINE 使用者
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

if __name__ == "__main__":
    app.run()
