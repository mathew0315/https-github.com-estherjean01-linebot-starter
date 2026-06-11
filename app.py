import os
import sys
import json
import threading

from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    ApiClient, Configuration, MessagingApi,
    ReplyMessageRequest, PushMessageRequest,
    FlexMessage, TextMessage
)
from google import genai
from google.genai import types

app = Flask(__name__)

LINE_CHANNEL_SECRET       = os.environ.get('LINE_CHANNEL_SECRET', '')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
GEMINI_API_KEY            = os.environ.get('GEMINI_API_KEY', '')

handler       = WebhookHandler(LINE_CHANNEL_SECRET)
line_config   = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

MIN_LENGTH      = 5
IGNORE_PREFIXES = []
MAX_INPUT_CHARS = 3000


def get_push_target(event):
    source = event.source
    src_type = getattr(source, 'type', None)
    if src_type == 'group':
        return getattr(source, 'group_id', None)
    elif src_type == 'room':
        return getattr(source, 'room_id', None)
    else:
        return getattr(source, 'user_id', None)


def build_flex_note(theme, summary, points, content_type="一般筆記"):
    point_rows = []
    for i, pt in enumerate(points, 1):
        point_rows.append({
            "type": "box", "layout": "horizontal", "spacing": "sm", "margin": "md",
            "contents": [
                {
                    "type": "box", "layout": "vertical", "width": "20px", "height": "20px",
                    "cornerRadius": "10px", "backgroundColor": "#5C5BE5",
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
    return {"altText": f"📋 {theme}：{summary}", "contents": bubble}


def build_waiting_flex():
    bubble = {
        "type": "bubble", "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "backgroundColor": "#EEF2FF",
            "paddingAll": "20px",
            "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "⏳", "size": "lg", "flex": 0},
                    {"type": "text", "text": "正在整理筆記", "size": "md",
                     "color": "#3B30CC", "weight": "bold", "margin": "md", "gravity": "center"}
                ]},
                {"type": "text",
                 "text": "AI 正在分析您的內容，請稍等片刻，結果會立即傳送給您。",
                 "size": "sm", "color": "#555577", "wrap": True,
                 "margin": "lg", "lineSpacing": "6px"}
            ]
        }
    }
    return {"altText": "⏳ AI 正在整理筆記，請稍候…", "contents": bubble}


def build_guide_flex(guide_text):
    bubble = {
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
                {"type": "text", "text": guide_text, "size": "sm", "color": "#555555",
                 "wrap": True, "margin": "md", "lineSpacing": "6px"}
            ]
        }
    }
    return {"altText": "💡 " + guide_text[:50], "contents": bubble}


def build_toolong_flex(char_count):
    bubble = {
        "type": "bubble", "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "backgroundColor": "#FFF4EC",
            "paddingAll": "16px",
            "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "✂️", "size": "md", "flex": 0},
                    {"type": "text", "text": "內容已自動截取", "size": "sm",
                     "color": "#CC6600", "weight": "bold", "margin": "sm"}
                ]},
                {"type": "text",
                 "text": (f"您的輸入共 {char_count} 字，超過 {MAX_INPUT_CHARS} 字上限。\n"
                          f"系統已自動截取前 {MAX_INPUT_CHARS} 字進行整理。\n\n"
                          "若需完整分析，請將內容分段後分次傳送。"),
                 "size": "sm", "color": "#555555", "wrap": True,
                 "margin": "md", "lineSpacing": "6px"}
            ]
        }
    }
    return {"altText": f"✂️ 內容已截取前 {MAX_INPUT_CHARS} 字進行整理", "contents": bubble}


def build_error_flex(error_text):
    bubble = {
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
    return {"altText": "⚠️ " + error_text[:50], "contents": bubble}


def _reply_flex(reply_token, payload):
    with ApiClient(line_config) as api_client:
        MessagingApi(api_client).reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[FlexMessage(alt_text=payload["altText"], contents=payload["contents"])]
        ))


def _push_flex(target_id, payload):
    with ApiClient(line_config) as api_client:
        MessagingApi(api_client).push_message(PushMessageRequest(
            to=target_id,
            messages=[FlexMessage(alt_text=payload["altText"], contents=payload["contents"])]
        ))


def _push_flex_list(target_id, payloads):
    with ApiClient(line_config) as api_client:
        MessagingApi(api_client).push_message(PushMessageRequest(
            to=target_id,
            messages=[FlexMessage(alt_text=p["altText"], contents=p["contents"])
                      for p in payloads]
        ))


def call_gemini(content):
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
- points 至少 1 條，最多 5 條
- 所有文字必須是繁體中文
- 只輸出 JSON，不能有任何其他文字
"""
    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1)
    )
    raw = response.text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def process_and_push(target_id, content, is_trimmed, original_len):
    try:
        result = call_gemini(content)
        payloads = []
        if is_trimmed:
            payloads.append(build_toolong_flex(original_len))
        if result.get("type") == "guide":
            payloads.append(build_guide_flex(result["message"]))
        else:
            payloads.append(build_flex_note(
                theme=result.get("theme", "筆記"),
                summary=result.get("summary", ""),
                points=result.get("points", []),
                content_type=result.get("content_type", "一般筆記")
            ))
        _push_flex_list(target_id, payloads)

    except json.JSONDecodeError as e:
        print(f"[JSONDecodeError] {e}", file=sys.stderr)
        _push_flex(target_id, build_error_flex("AI 回應格式異常，請再試一次。"))

    except Exception as e:
        err = str(e)
        print(f"[Error] {err}", file=sys.stderr)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            msg = "免費 API 呼叫太頻繁，請等待約半分鐘後再試一次。"
        elif "503" in err or "overloaded" in err.lower():
            msg = "AI 伺服器負載較高，請稍等一分鐘後再傳送一次。"
        elif "timeout" in err.lower():
            msg = "AI 回應逾時，請將內容裁短後分段傳送。"
        else:
            msg = f"系統異常。\n錯誤詳情：{err[:150]}"
        _push_flex(target_id, build_error_flex(msg))


@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_msg = event.message.text.strip()

    if len(user_msg) < MIN_LENGTH:
        return
    for prefix in IGNORE_PREFIXES:
        if user_msg.startswith(prefix):
            return

    target_id = get_push_target(event)
    if not target_id:
        print("[Warning] Cannot get push target id, skipping.", file=sys.stderr)
        return

    original_len = len(user_msg)
    is_trimmed   = original_len > MAX_INPUT_CHARS
    content      = user_msg[:MAX_INPUT_CHARS] if is_trimmed else user_msg

    try:
        _reply_flex(event.reply_token, build_waiting_flex())
    except Exception as e:
        print(f"[reply failed] {e}", file=sys.stderr)

    threading.Thread(
        target=process_and_push,
        args=(target_id, content, is_trimmed, original_len),
        daemon=True
    ).start()


@app.route("/", methods=['GET'])
def health_check():
    return "LINE Bot is running.", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

