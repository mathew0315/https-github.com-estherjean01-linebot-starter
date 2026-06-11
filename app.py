import os
import sys
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from google import genai
from google.genai import types

app = Flask(__name__)

# 讀取環境變數
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

    # 1. 定義觸發關鍵字
    trigger_keywords = ["/筆記", "整理：", "幫我讀"]
    target_content = ""
    is_triggered = False

    for keyword in trigger_keywords:
        if user_msg.startswith(keyword):
            is_triggered = True
            target_content = user_msg[len(keyword):].strip()
            break

    # 2. 未觸發關鍵字，直接中斷執行
    if not is_triggered:
        return

    # 3. 觸發了指令，但沒有提供內容
    if not target_content:
        reply_text = "已收到指令。請在關鍵字後方提供需要整理的內容。\n範例：/筆記 下午三點要開行銷會議。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 4. 執行核心閱讀與筆記邏輯
    try:
        prompt = f"""
        任務：獨立閱讀並結構化產出筆記，或給予補充提示。
        輸入內容：{target_content}
        
        強制規則：
        1. 絕對不准使用星號或任何 Markdown 符號排版。
        2. 絕對不准產生開場白或結語，輸出必須冷靜客觀。
        3. 請先評估「輸入內容」的資訊量：
           - 若內容空泛、缺乏具體細節（如：只有人名、無意義字詞），請在第一行輸出 [GUIDE]，第二行直接點出欠缺的要素，要求補充。
           - 若內容有實質意義，請直接依照以下格式輸出筆記：
        
        【主題定調】
        (用一個詞或短句定義內容屬性)
        
        【重點摘要】
        (一句話精準總結)
        
        【筆記梳理】
        1. (重點拆解)
        2. (重點拆解)
        (若無具體重點則寫：無延伸重點)
        """
        
        # 改回正確的 2.5 版模型
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1) 
        )
        
        if response and response.text:
            raw_reply = response.text.strip()
            
            if "[GUIDE]" in raw_reply:
                reply_text = raw_reply.replace("[GUIDE]", "").strip()
            else:
                reply_text = raw_reply
        else:
            reply_text = "分析中斷。API 連線成功，但未回傳有效文字。"

    except Exception as e:
        error_msg = str(e)
        print(f"API Error: {error_msg}", file=sys.stderr)
        
        # 新增 503 塞車防護機制
        if "503" in error_msg:
            reply_text = "目前 AI 伺服器負載較高，請稍等一分鐘後再傳送一次。"
        else:
            reply_text = f"系統連線異常。\n錯誤詳情：{error_msg}"

    # 5. 將最終結果發送回 LINE
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    app.run()
