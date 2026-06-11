import os
import sys
import json
import threading

from flask import Flask, request, abort

# ── LINE Bot SDK v3（正確寫法）────────────────────────────────
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    ApiClient, Configuration, MessagingApi,
    ReplyMessageRequest, PushMessageRequest,
    FlexMessage
)

# ── Google Gemini ─────────────────────────────────────────────
from google import genai
from google.genai import types

# ══════════════════════════════════════════════════════════════
# 初始化
# ══════════════════════════════════════════════════════════════
app = Flask(__name__)

LINE_CHANNEL_SECRET       = os.environ.get('LINE_CHANNEL_SECRET', '')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
GEMINI_API_KEY            = os.environ.get('GEMINI_API_KEY', '')

handler       = WebhookHandler(LINE_CHANNEL_SECRET)
line_config   = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# ══════════════════════════════════════════════════════════════
# 設定常數
# ══════════════════════════════════════════════════════════════
MIN_LENGTH      = 5           # 少於此字數不處理
IGNORE_PREFIXES = ["/", "!"]  # 以這些字元開頭的訊息不處理
MAX_INPUT_CHARS = 3000        # 超過此字數自動截取


# ══════════════════════════════════════════════════════════════
# Flex Message 建構器
# ══════════════════════════════════════════════════════════════

def build_flex_note(theme: str, summary: str, points: list,
                    content_type: str = "一般筆記") -> dict:
    """筆記結果卡片（紫色主題，帶圓形序號）"""
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
                    "contents": [{
                        "type": "text",
                        "text": str(i),
                        "size": "xxs",
                        "color": "#FFFFFF",
                        "align": "center",
                        "gravity": "center"
                    }]
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
                        {"type": "text", "text": "📋", "size": "sm", "flex": 0},
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
                {"type": "separator", "margin": "md", "color": "#E0E0F0"},
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
    return {"altText": f"📋 {theme}：{summary}", "contents": bubble}


def build_waiting_flex() -> dict:
    """等待中提示卡片（藍色，立即回覆讓用戶知道在處理中）"""
    bubble = {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#EEF2FF",
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "⏳", "size": "lg", "flex": 0},
                        {
                            "type": "text",
                            "text": "正在整理筆記",
                            "size": "md",
                            "color": "#3B30CC",
                            "weight": "bold",
                            "margin": "md",
                            "gravity": "center"
                        }
                    ]
                },
                {
                    "type": "text",
                    "text": "AI 正在分析您的內容，請稍等片刻，結果會立即傳送給您。",
                    "size": "sm",
                    "color": "#555577",
                    "wrap": True,
                    "margin": "lg",
                    "lineSpacing": "6px"
                }
            ]
        }
    }
    return {"altText": "⏳ AI 正在整理筆記，請稍候…", "contents": bubble}


def build_guide_flex(guide_text: str) -> dict:
    """引導補充訊息卡片（黃色，資訊不足時使用）"""
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
                        {"type": "text", "text": "💡", "size": "md", "flex": 0},
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
    return {"altText": "💡 " + guide_text[:50], "contents": bubble}


def build_toolong_flex(char_count: int) -> dict:
    """輸入過長提示卡片（橘色，截取後自動附上）"""
    bubble = {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#FFF4EC",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "✂️", "size": "md", "flex": 0},
                        {
                            "type": "text",
                            "text": "內容已自動截取",
                            "size": "sm",
                            "color": "#CC6600",
                            "weight": "bold",
                            "margin": "sm"
                        }
                    ]
                },
                {
                    "type": "text",
                    "text": (
                        f"您的輸入共 {char_count} 字，超過 {MAX_INPUT_CHARS} 字上限。\n"
                        f"系統已自動截取前 {MAX_INPUT_CHARS} 字進行整理。\n\n"
                        "若需完整分析，請將內容分段後分次傳送。"
                    ),
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
        "altText": f"✂️ 內容已截取前 {MAX_INPUT_CHARS} 字進行整理",
        "contents": bubble
    }


def build_error_flex(error_text: str) -> dict:
    """錯誤提示卡片（紅色）"""
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
                        {"type": "text", "text": "⚠️", "size": "md", "flex": 0},
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
    return {"altText": "⚠️ " + error_text[:50], "contents": bubble}


# ══════════════════════════════════════════════════════════════
# Gemini API 呼叫
# ══════════════════════════════════════════════════════════════

def call_gemini(content: str) -> dict:
    """
    呼叫 Gemini 2.5 Flash，要求以純 JSON 回傳結構化筆記。

    成功回傳：
      { "type": "note", "content_type": str, "theme": str,
        "summary": str, "points": [str, ...] }

    資訊不足回傳：
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

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1)
    )

    raw = response.text.strip()
    # 清除 AI 可能夾帶的 markdown code fence
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ══════════════════════════════════════════════════════════════
# 輔助：傳送 FlexMessage
# ══════════════════════════════════════════════════════════════

def _reply_flex(reply_token: str, payload: dict):
    """以 reply_message 回覆（需在 30 秒內，用於等待卡片）"""
    with ApiClient(line_config) as api_client:
        api = MessagingApi(api_client)
        api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[FlexMessage(
                alt_text=payload["altText"],
                contents=payload["contents"]
            )]
        ))


def _push_flex(user_id: str, payload: dict):
    """以 push_message 主動推送（不受 reply token 時效限制）"""
    with ApiClient(line_config) as api_client:
        api = MessagingApi(api_client)
        api.push_message(PushMessageRequest(
            to=user_id,
            messages=[FlexMessage(
                alt_text=payload["altText"],
                contents=payload["contents"]
            )]
        ))


def _push_flex_list(user_id: str, payloads: list):
    """一次推送多則 FlexMessage（最多 5 則）"""
    with ApiClient(line_config) as api_client:
        api = MessagingApi(api_client)
        api.push_message(PushMessageRequest(
            to=user_id,
            messages=[
                FlexMessage(alt_text=p["altText"], contents=p["contents"])
                for p in payloads
            ]
        ))


# ══════════════════════════════════════════════════════════════
# 非同步 AI 處理（獨立執行緒 + push_message）
# 解決 Render 免費方案延遲導致 reply token 過期的問題
# ══════════════════════════════════════════════════════════════

def process_and_push(user_id: str, content: str,
                     is_trimmed: bool, original_len: int):
    """
    在獨立執行緒中呼叫 Gemini，完成後以 push_message 傳送結果。
    完全不受 reply token 30 秒限制。
    """
    try:
        result = call_gemini(content)

        payloads_to_send = []

        # 若內容被截取，先附上截取通知
        if is_trimmed:
            payloads_to_send.append(build_toolong_flex(original_len))

        # 附上筆記或引導卡片
        if result.get("type") == "guide":
            payloads_to_send.append(build_guide_flex(result["message"]))
        else:
            payloads_to_send.append(build_flex_note(
                theme=result.get("theme", "筆記"),
                summary=result.get("summary", ""),
                points=result.get("points", []),
                content_type=result.get("content_type", "一般筆記")
            ))

        _push_flex_list(user_id, payloads_to_send)

    except json.JSONDecodeError as e:
        print(f"[JSONDecodeError] {e}", file=sys.stderr)
        _push_flex(user_id, build_error_flex("AI 回應格式異常，請再試一次。"))

    except Exception as e:
        error_msg = str(e)
        print(f"[API Error] {error_msg}", file=sys.stderr)

        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
            msg = "免費 API 呼叫太頻繁，請等待約半分鐘後再試一次。"
        elif "503" in error_msg or "overloaded" in error_msg.lower():
            msg = "AI 伺服器負載較高，請稍等一分鐘後再傳送一次。"
        elif "timeout" in error_msg.lower():
            msg = "AI 回應逾時，內容可能過長。請裁短後分段傳送。"
        else:
            msg = f"系統連線異常。\n錯誤詳情：{error_msg[:150]}"

        _push_flex(user_id, build_error_flex(msg))


# ══════════════════════════════════════════════════════════════
# Webhook 路由
# ══════════════════════════════════════════════════════════════

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
    user_id  = event.source.user_id

    # ── 過濾：太短的訊息（問候語、ok 等）
    if len(user_msg) < MIN_LENGTH:
        return

    # ── 過濾：其他機器人指令前綴
    for prefix in IGNORE_PREFIXES:
        if user_msg.startswith(prefix):
            return

    # ── 輸入長度檢查
    original_len = len(user_msg)
    is_trimmed   = original_len > MAX_INPUT_CHARS
    content      = user_msg[:MAX_INPUT_CHARS] if is_trimmed else user_msg

    # ── 步驟 1：立即 reply 等待提示（消耗 reply token，必須在 30 秒內）
    try:
        _reply_flex(event.reply_token, build_waiting_flex())
    except Exception as e:
        # Render 冷啟動時 reply token 可能已過期，記錄後繼續
        print(f"[reply waiting card failed] {e}", file=sys.stderr)

    # ── 步驟 2：背景執行緒呼叫 Gemini，完成後 push 結果
    threading.Thread(
        target=process_and_push,
        args=(user_id, content, is_trimmed, original_len),
        daemon=True
    ).start()


# ══════════════════════════════════════════════════════════════
# 健康檢查（Render / Railway 需要此端點）
# ══════════════════════════════════════════════════════════════

@app.route("/", methods=['GET'])
def health_check():
    return "LINE Bot is running.", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
