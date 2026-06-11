import os
import sys
import json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, FlexSendMessage
from google import genai
from google.genai import types

app = Flask(__name__)

LINE_CHANNEL_SECRET     = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_API_KEY          = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler      = WebhookHandler(LINE_CHANNEL_SECRET)
client       = genai.Client(api_key=GEMINI_API_KEY)

# ──────────────────────────────────────────────────────────────
# 訊息過濾設定（群組使用建議將 MIN_LENGTH 調高至 20）
# ──────────────────────────────────────────────────────────────
MIN_LENGTH      = 5          # 少於此字數不處理（過濾「ok」「好」等短回覆）
IGNORE_PREFIXES = ["/", "!"] # 以這些字元開頭的訊息不處理（避免干擾其他機器人）

# ──────────────────────────────────────────────────────────────
# Flex Message 建構器
# ──────────────────────────────────────────────────────────────

def build_flex_note(theme: str, summary: str, points: list,
                    content_type: str = "一般筆記") -> dict:
    """建立筆記卡片 Flex Message（紫色主題，帶圓形序號）"""

    point_rows = []
    for i, pt in enumerate(points, 1):
        point_rows.append({
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "margin": "md",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "width": "20px",
                    "height": "20px",
                    "cornerRadius": "10px",
                    "backgroundColor": "#5C5BE5",
                    "justifyContent": "center",
                    "alignItems": "center",
                    "contents": [
                        {
                            "type": "text",
                            "text": str(i),
                            "size": "xxs",
                            "color": "#FFFFFF",
                            "align": "center",
                            "gravity": "center"
                        }
                    ]
                },
                {
                    "type": "text",
                    "text": pt,
                    "size": "sm",
                    "color": "#333333",
                    "flex": 1,
                    "wrap": True,
                    "lineSpacing": "4px"
                }
            ]
        })

    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#5C5BE5",
            "paddingAll": "16px",
            "paddingBottom": "12px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "📋",
                            "size": "sm",
                            "flex": 0
                        },
                        {
                            "type": "text",
                            "text": content_type,
                            "size": "xs",
                            "color": "#C8C6FF",
                            "flex": 1,
                            "margin": "sm"
                        }
                    ]
                },
                {
                    "type": "text",
                    "text": theme,
                    "size": "xl",
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "wrap": True,
                    "margin": "sm"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F8F8FC",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#EEEEFF",
                    "cornerRadius": "8px",
                    "paddingAll": "12px",
                    "contents": [
                        {
                            "type": "text",
                            "text": "核心摘要",
                            "size": "xs",
                            "color": "#5C5BE5",
                            "weight": "bold"
                        },
                        {
                            "type": "text",
                            "text": summary,
                            "size": "sm",
                            "color": "#333333",
                            "wrap": True,
                            "margin": "sm",
                            "lineSpacing": "6px"
                        }
                    ]
                },
                {
                    "type": "separator",
                    "margin": "md",
                    "color": "#E0E0F0"
                },
                {
                    "type": "text",
                    "text": "重點梳理",
                    "size": "xs",
                    "color": "#888888",
                    "weight": "bold",
                    "margin": "md"
                },
                *point_rows
            ]
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "backgroundColor": "#F0F0F8",
            "paddingAll": "10px",
            "contents": [
                {
                    "type": "text",
                    "text": "由 AI 自動整理",
                    "size": "xxs",
                    "color": "#AAAACC",
                    "flex": 1
                },
                {
                    "type": "text",
                    "text": "長按可複製筆記",
                    "size": "xxs",
                    "color": "#AAAACC",
                    "align": "end"
                }
            ]
        },
        "styles": {
            "header": {"separator": False},
            "footer": {"separator": True, "separatorColor": "#E0E0F0"}
        }
    }

    return {
        "type": "flex",
        "altText": f"📋 {theme}：{summary}",
        "contents": bubble
    }


def build_guide_flex(guide_text: str) -> dict:
    """建立引導補充訊息卡片（黃色，資訊不足時使用）"""
    bubble = {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#FFF8EE",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "💡",
                            "size": "md",
                            "flex": 0
                        },
                        {
                            "type": "text",
                            "text": "需要更多資訊",
                            "size": "sm",
                            "color": "#C47800",
                            "weight": "bold",
                            "margin": "sm"
                        }
                    ]
                },
                {
                    "type": "text",
                    "text": guide_text,
                    "size": "sm",
                    "color": "#555555",
                    "wrap": True,
                    "margin": "md",
                    "lineSpacing": "6px"
                }
            ]
        }
    }
    return {
        "type": "flex",
        "altText": "💡 " + guide_text[:50],
        "contents": bubble
    }


def build_error_flex(error_text: str) -> dict:
    """建立錯誤提示卡片（紅色）"""
    bubble = {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#FFF0F0",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "⚠️",
                            "size": "md",
                            "flex": 0
                        },
                        {
                            "type": "text",
                            "text": "系統提示",
                            "size": "sm",
                            "color": "#CC3333",
                            "weight": "bold",
                            "margin": "sm"
                        }
                    ]
                },
                {
                    "type": "text",
                    "text": error_text,
                    "size": "sm",
                    "color": "#555555",
                    "wrap": True,
                    "margin": "md",
                    "lineSpacing": "6px"
                }
            ]
        }
    }
    return {
        "type": "flex",
        "altText": "⚠️ " + error_text[:50],
        "contents": bubble
    }


# ──────────────────────────────────────────────────────────────
# Gemini API 呼叫
# ──────────────────────────────────────────────────────────────

def call_gemini(content: str) -> dict:
    """
    呼叫 Gemini 2.5 Flash，要求以純 JSON 回傳結構化筆記。

    成功回傳格式：
      { "type": "note", "content_type": str, "theme": str,
        "summary": str, "points": [str, ...] }

    資訊不足時回傳：
      { "type": "guide", "message": str }
    """
    prompt = f"""
你是一位專業的中文筆記整理助手。請仔細閱讀以下「輸入內容」，然後依照規則回傳 JSON。

輸入內容：
{content}

===規則===
1. 先評估輸入是否有實質資訊量。
   - 若輸入空泛（只有人名、無意義字元、少於10字的問候語），請回傳：
     {{"type":"guide","message":"請補充更多內容，例如：發生了什麼事？時間地點？需要記錄哪些細節？"}}
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
- points 至少 1 條，最多 5 條，視內容豐富度決定
- 所有文字必須是繁體中文
- 只輸出 JSON，不能有任何其他文字
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1)
    )

    raw = response.text.strip()
    # 清除 AI 可能夾帶的 markdown code fence
    raw = raw.replace("```json", "").replace("```", "").strip()

    return json.loads(raw)


# ──────────────────────────────────────────────────────────────
# Webhook 路由
# ──────────────────────────────────────────────────────────────

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

    # ── 過濾：太短的訊息直接忽略（問候語、貼圖說明等）
    if len(user_msg) < MIN_LENGTH:
        return

    # ── 過濾：其他機器人指令前綴
    for prefix in IGNORE_PREFIXES:
        if user_msg.startswith(prefix):
            return

    # ── 呼叫 AI 並回覆
    try:
        result = call_gemini(user_msg)

        if result.get("type") == "guide":
            flex_payload = build_guide_flex(result["message"])
        else:
            flex_payload = build_flex_note(
                theme=result.get("theme", "筆記"),
                summary=result.get("summary", ""),
                points=result.get("points", []),
                content_type=result.get("content_type", "一般筆記")
            )

        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text=flex_payload["altText"],
                contents=flex_payload["contents"]
            )
        )

    except json.JSONDecodeError as e:
        print(f"JSON Parse Error: {e}", file=sys.stderr)
        _send_error(event.reply_token, "AI 回應格式異常，請再試一次。")

    except Exception as e:
        error_msg = str(e)
        print(f"API Error: {error_msg}", file=sys.stderr)

        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
            _send_error(event.reply_token,
                        "免費 API 呼叫太頻繁，請等待約半分鐘後再試一次。")
        elif "503" in error_msg:
            _send_error(event.reply_token,
                        "AI 伺服器負載較高，請稍等一分鐘後再傳送一次。")
        else:
            _send_error(event.reply_token,
                        f"系統連線異常。\n錯誤詳情：{error_msg}")


def _send_error(reply_token: str, message: str):
    """統一的錯誤回覆輔助函式"""
    flex_payload = build_error_flex(message)
    line_bot_api.reply_message(
        reply_token,
        FlexSendMessage(
            alt_text=flex_payload["altText"],
            contents=flex_payload["contents"]
        )
    )


if __name__ == "__main__":
    app.run()
