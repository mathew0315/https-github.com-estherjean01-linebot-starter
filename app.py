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
    reply_text = ""

    # 1. 觸發指令與內容分離
    trigger_keywords = ["/筆記", "整理：", "幫我讀"]
    target_content = ""
    is_triggered = False

    for keyword in trigger_keywords:
        if user_msg.startswith(keyword):
            is_triggered = True
            target_content = user_msg[len(keyword):].strip()
            break

    # 2. 防呆攔截：沒呼叫指令
    if not is_triggered:
        reply_text = "我收到訊息了。若需要整理筆記，請在文字前加上關鍵字。\n範例：/筆記 明天下午開會討論預算。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 3. 防呆攔截：有指令但完全沒內容
    if not target_content:
        reply_text = "請提供具體內容。\n範例：/筆記 今天客戶說功能要修改。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 4. 核心處理邏輯
    try:
        prompt = f"""
        任務：獨立閱讀並結構化產出筆記，或給予補充提示。
        輸入內容：{target_content}
        
        強制規則：
        1. 絕對不准使用星號或任何 Markdown 符號排版。
        2. 絕對不准產生開場白或結語。
        3. 請先評估「輸入內容」的資訊量：
           - 若內容毫無邏輯、極度空泛或缺乏具體細節，請在第一行輸出 [GUIDE]，第二行直接點出欠缺的要素，要求使用者補充（例如：缺乏具體事件，請補充相關人事時地物）。
           - 若內容有實質意義，請直接依照以下格式輸出筆記：
        
        【主題定調】
        (用一個詞定義內容屬性)
        
        【重點摘要】
        (一句話精準總結)
        
        【筆記梳理】
        1. (重點1)
        2. (重點2)
        """
        
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1) 
        )
        
        # 捕捉 AI 生成結果，防止空值或安全審查阻擋
        if response and response.text:
            raw_reply = response.text.strip()
            
            if "[GUIDE]" in raw_reply:
                reply_text = raw_reply.replace("[GUIDE]", "").strip()
            else:
                reply_text = raw_reply
        else:
            reply_text = "分析中斷。內容可能涉及安全過濾，或 API 回傳空白。"

    except Exception as e:
        error_msg = str(e)
        print(f"API Error: {error_msg}", file=sys.stderr)
        reply_text = f"系統連線異常，無法製作筆記。\n真實報錯原因：{error_msg}"

    # 無論上面發生什麼事，最後絕對會執行這行，確保不會已讀不回
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    app.run()
