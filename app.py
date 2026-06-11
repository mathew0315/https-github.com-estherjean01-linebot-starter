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

    # 1. 觸發指令與內容分離
    trigger_keywords = ["/筆記", "整理：", "幫我讀"]
    target_content = ""
    is_triggered = False

    for keyword in trigger_keywords:
        if user_msg.startswith(keyword):
            is_triggered = True
            target_content = user_msg[len(keyword):].strip()
            break

    # 沒呼叫指令，機器人保持沉默
    if not is_triggered:
        return

    # 2. 第一層防呆：有指令但完全沒內容
    if not target_content:
        reply_text = "請提供具體內容。\n範例：/筆記 明天下午三點開會，討論行銷預算，記得帶報表。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 3. 核心處理邏輯
    try:
        prompt = f"""
        任務：獨立閱讀並結構化產出筆記，或給予補充提示。
        輸入內容：{target_content}
        
        強制規則：
        1. 絕對不准使用星號或任何 Markdown 符號排版。
        2. 絕對不准產生開場白或結語。
        3. 請先評估「輸入內容」的資訊量：
           - 若內容毫無邏輯、極度空泛或缺乏具體細節（如：只有人名、單純的情緒發洩、無意義字詞），請在第一行輸出 [GUIDE]，第二行直接點出欠缺的要素，要求使用者補充（例如：缺乏具體事件，請補充人事時地物或待辦事項）。
           - 若內容有實質意義，請直接依照以下格式輸出筆記：
        
        【主題定調】
        (用一個詞定義，如：會議、待辦、隨記、程式碼)
        
        【重點摘要】
        (一句話精準總結)
        
        【筆記梳理】
        1. (擷取重點1)
        2. (擷取重點2)
        """
        
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1) 
        )
        
        if response and response.text:
            raw_reply = response.text.strip()
            
            # 解析 AI 的判斷結果
            if "[GUIDE]" in raw_reply:
                # 資訊不足，給予 AI 產生的引導提示
                reply_text = raw_reply.replace("[GUIDE]", "").strip()
            else:
                # 資訊充足，給出整理好的筆記
                reply_text = raw_reply
        else:
            reply_text = "分析中斷。請確認輸入的文字是否過短或包含無法解析的符號。"

    except Exception as e:
        print(f"API Error: {e}", file=sys.stderr)
        # 捕捉真正的系統錯誤，並給出實用的備用方案
        reply_text = "系統連線異常，無法製作筆記。請先將這段文字複製備份，稍後再試。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    app.run()
