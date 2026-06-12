import os
import sys
import json
import threading

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
from google import genai
from google.genai import types

app = Flask(__name__)

LINE_CHANNEL_SECRET       = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_API_KEY            = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler      = WebhookHandler(LINE_CHANNEL_SECRET)
client       = genai.Client(api_key=GEMINI_API_KEY)

MIN_LENGTH      = 5
MAX_INPUT_CHARS = 3000


def build_flex_note(theme, summary, points, content_type="一般筆記"):
    point_rows = []
    for i, pt in enumerate(points, 1):
        point_rows.append({
            "type": "box", "layout": "horizontal", "spacing": "sm", "margin": "md",
            "contents": [
                {
                    "type": "box", "layout": "vertical",
                    "width": "20px", "height": "20px", "cornerRadius": "10px",
                    "backgroundColor": "#5C5BE5",
                    "justifyContent": "center", "alignItems": "center",
                    "contents": [{"type": "text", "text": str(i), "size": "xxs",
                                  "color": "#FFFFFF", "align": "center", "gravity": "center"}]
                },
                {"type": "text", "text": pt, "size": "sm", "color": "#333333",
                 "flex": 1, "wrap": True, "lineSpacing": "4px"}
            ]
        })
    bubble = {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#5C5BE5",
            "paddingAll": "16px", "paddingBottom": "12px",
            "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "📋", "size": "sm", "flex": 0},
                    {"type": "text", "text": content_type, "size": "xs",
                     "color": "#C8C6FF", "flex": 1, "margin": "sm"}
                ]},
                {"type": "text", "text": theme, "size": "xl", "color": "#FFFFFF",
                 "weight": "bold", "wrap": True, "margin": "sm"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "backgroundColor": "#F8F8FC",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "box", "layout": "vertical", "backgroundColor": "#EEEEFF",
                    "cornerRadius": "8px", "paddingAll": "12px",
                    "contents": [
                        {"type": "text", "text": "核心摘要", "size": "xs",
                         "color": "#5C5BE5", "weight": "bold"},
                        {"type": "text", "text": summary, "size": "sm", "color": "#333333",
                         "wrap": True, "margin": "sm", "lineSpacing": "6px"}
                    ]
                },
                {"type": "separator", "margin": "md", "color": "#E0E0F0"},
                {"type": "text", "text": "重點梳理", "size": "xs",
                 "color": "#888888", "weight": "bold", "margin": "md"},
                *point_rows
            ]
        },
        "footer": {
            "type": "box", "layout": "horizontal", "backgroundColor": "#F0F0F8",
            "paddingAll": "10px",
            "contents": [
                {"type": "text", "text": "由 AI 自動整理", "size": "xxs",
                 "color": "#AAAACC", "flex": 1},
                {"type": "text", "text": "長按可複製筆記", "size": "xxs",
                 "color": "#AAAACC", "align": "end"}
            ]
        },
        "styles": {"header": {"separator": False},
                   "footer": {"separator": True, "separatorColor": "#E0E0F0"}}
    }
    return bubble


def build_guide_bubble():
    return {
        "type": "bubble", "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "backgroundColor": "#FFF8EE",
            "paddingAll": "16px",
            "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "💡", "size": "md", "flex": 0},
                    {"type": "text", "text": "需要更多資訊", "size": "sm",
                     "color": "#C47800", "weight": "bold", "margin": "sm"}
                ]},
                {"type": "text",
                 "text": "請補充更多內容，例如：發生了什麼事？時間地點？需要記錄哪些細節？",
                 "size": "sm", "color": "#555555", "wrap": True,
                 "margin": "md", "lineSpacing": "6px"}
            ]
        }
    }


def build_error_bubble(error_text):
    return {
        "type": "bubble", "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "backgroundColor": "#FFF0F0",
            "paddingAll": "16px",
            "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "⚠️", "size": "md", "flex": 0},
                    {"type": "text", "text": "系統提示", "size": "sm",
                     "color": "#CC3333", "weight": "bold", "margin": "sm"}
                ]},
                {"type": "text", "text": error_text, "size": "sm", "color": "#555555",
                 "wrap": True, "margin": "md", "lineSpacing": "6px"}
            ]
        }
    }


def call_gemini(content):
    prompt = f"""
你是一位專業的中文筆記整理助手。請仔細閱讀以下「輸入內容」，然後依照規則回傳 JSON。

輸入內容：
{content}

===規則===
1. 先評估輸入是否有實質資訊量。
   - 若輸入空泛（只有人名、無意義字元、少於10字的問候語），請回傳：
     {{"type":"guide"}}
   - 若有實質內容，繼續下一步。

2. 判斷輸入類型，填入 content_type（必須為以下之一）：
   「會議記錄」「新聞資訊」「學習筆記」「待辦事項」「聊天摘要」「條文規定」「數據報告」「一般筆記」

3. 回傳以下格式的純 JSON（不含任何 markdown、開場白或說明文字）：
{{
  "type": "note",
  "content_type": "<類型>",
  "theme": "<5字以內的主題標題>",
  "summary": "<一句話精準總結，30字以內>",
  "points": [
    "<重點1，15字以內>",
    "<重點2，15字以內>",
    "<重點3，15字以內（可選）>",
    "<重點4，15字以內（可選）>",
    "<重點5，15字以內（可選）>"
  ]
}}

注意事項：
- points 至少 1 條，最多 5 條
- 所有文字必須是繁體中文
- 只輸出 JSON，不能有任何其他文字
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1)
    )
    raw = response.text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()

    if len(user_msg) < MIN_LENGTH:
        return

    content = user_msg[:MAX_INPUT_CHARS]

    try:
        result = call_gemini(content)

        if result.get("type") == "guide":
            flex_msg = FlexSendMessage(
                alt_text="💡 請補充更多資訊",
                contents=build_guide_bubble()
            )
        else:
            flex_msg = FlexSendMessage(
                alt_text=f"📋 {result.get('theme', '筆記')}",
                contents=build_flex_note(
                    theme=result.get("theme", "筆記"),
                    summary=result.get("summary", ""),
                    points=result.get("points", []),
                    content_type=result.get("content_type", "一般筆記")
                )
            )

    except Exception as e:
        err = str(e)
        print(f"[Error] {err}", file=sys.stderr)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            msg = "API 呼叫太頻繁，請等待約半分鐘後再試。"
        elif "503" in err or "overloaded" in err.lower():
            msg = "AI 伺服器忙碌，請稍等一分鐘後再試。"
        else:
            msg = f"系統異常：{err[:100]}"
        flex_msg = FlexSendMessage(
            alt_text="⚠️ 系統提示",
            contents=build_error_bubble(msg)
        )

    line_bot_api.reply_message(event.reply_token, flex_msg)


@app.route("/", methods=['GET'])
def health_check():
    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
