import os
import sys
import json

from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError

from linebot.models import (
    MessageEvent,
    TextMessage,
    TextSendMessage,
    FlexSendMessage,
    QuickReply,
    QuickReplyButton,
    MessageAction
)

from google import genai
from google.genai import types


app = Flask(__name__)


# ==========================
# LINE 設定
# ==========================

LINE_CHANNEL_SECRET = os.environ.get(
    "LINE_CHANNEL_SECRET"
)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get(
    "LINE_CHANNEL_ACCESS_TOKEN"
)


# ==========================
# Gemini
# ==========================

GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY"
)


client = genai.Client(
    api_key=GEMINI_API_KEY
)



line_bot_api = LineBotApi(
    LINE_CHANNEL_ACCESS_TOKEN
)


handler = WebhookHandler(
    LINE_CHANNEL_SECRET
)



# ==========================
# 使用者狀態
# ==========================

user_sessions = {}



# ==========================
# AI 呼叫
# ==========================


def get_ai_response(prompt):

    result = client.models.generate_content(

        model="gemini-2.5-flash",

        contents=prompt,

        config=types.GenerateContentConfig(
            temperature=0.2
        )

    )


    return result.text



# ==========================
# JSON 安全解析
# ==========================


def parse_json(text):

    try:

        return json.loads(text)

    except:

        return {

            "title":"分析完成",

            "summary":text,

            "cta":"繼續"

        }




# ==========================
# LINE Flex UI
# ==========================


def create_card(data, stage):


    title = data.get(
        "title",
        "AI 學習挑戰"
    )


    summary = data.get(
        "summary",
        ""
    )


    task = data.get(
        "task",
        data.get(
            "cta",
            "請輸入答案"
        )
    )


    body = {

        "type":"bubble",

        "header":{

            "type":"box",

            "layout":"vertical",

            "contents":[

                {

                "type":"text",

                "text":
                f"挑戰進度 {stage}/4",

                "weight":"bold",

                "size":"sm"

                }

            ]

        },


        "body":{

            "type":"box",

            "layout":"vertical",

            "spacing":"md",

            "contents":[


                {

                "type":"text",

                "text":title,

                "weight":"bold",

                "size":"xl"

                },


                {

                "type":"text",

                "text":summary,

                "wrap":True

                },


                {

                "type":"separator"

                },


                {

                "type":"text",

                "text":
                "下一步",

                "weight":"bold"

                },


                {

                "type":"text",

                "text":task,

                "wrap":True

                }


            ]

        }

    }



    return FlexSendMessage(

        alt_text=title,

        contents=body

    )





# ==========================
# Quick Reply
# ==========================


def quick_buttons(options):


    return QuickReply(

        items=[


            QuickReplyButton(

                action=MessageAction(

                    label=x,

                    text=x

                )

            )

            for x in options


        ]

    )





# ==========================
# Webhook
# ==========================



@app.route(
    "/webhook",
    methods=["POST"]
)


def webhook():


    signature = request.headers[
        "X-Line-Signature"
    ]


    body = request.get_data(
        as_text=True
    )


    try:

        handler.handle(
            body,
            signature
        )


    except InvalidSignatureError:

        abort(400)



    return "OK"






# ==========================
# Message Handler
# ==========================



@handler.add(
    MessageEvent,
    message=TextMessage
)


def handle_message(event):


    user_id = event.source.user_id


    msg = event.message.text.strip()



    if msg == "重新開始":


        user_sessions[user_id] = {

            "state":0,

            "history":""

        }


        line_bot_api.reply_message(

            event.reply_token,

            TextSendMessage(

                text="新的挑戰已建立，請輸入題目。"

            )

        )


        return





    if user_id not in user_sessions:


        user_sessions[user_id]={

            "state":0,

            "history":""

        }





    session=user_sessions[user_id]


    state=session["state"]



    try:



        # ==========================
        # 第1關
        # ==========================


        if state==0:


            prompt=f"""

你是商業化 AI 教學產品。

請只輸出 JSON。

格式:

{{
"title":"",
"summary":"",
"task":"",
"optionA":"",
"optionB":""
}}


分析題目:

{msg}

不要直接給答案。

"""


            data=parse_json(
                get_ai_response(prompt)
            )


            session["history"] += str(data)


            session["state"]=1



            reply=create_card(
                data,
                1
            )


            qr=quick_buttons(
                [
                    "A",
                    "B"
                ]
            )


        # ==========================
        # 第2關
        # ==========================


        elif state==1:



            prompt=f"""

你是學習教練。

判斷使用者選擇。

輸出JSON:

{{
"title":"",
"summary":"",
"task":"",
"result":"correct/wrong"
}}


歷史:

{session["history"]}


回答:

{msg}

"""


            data=parse_json(
                get_ai_response(prompt)
            )



            if data.get(
                "result"
            )=="correct":


                session["state"]=2



            reply=create_card(
                data,
                2
            )


            qr=quick_buttons(
                [
                    "重新回答"
                ]
            )



        # ==========================
        # 第3關
        # ==========================


        elif state==2:



            prompt=f"""

驗證使用者計算。

JSON輸出:

{{
"title":"",
"summary":"",
"task":"",
"result":"correct/wrong"
}}

資料:

{session["history"]}

答案:

{msg}

"""


            data=parse_json(
                get_ai_response(prompt)
            )


            if data.get(
                "result"
            )=="correct":


                session["state"]=3



            reply=create_card(
                data,
                3
            )


            qr=quick_buttons(
                [
                    "挑戰"
                ]
            )



        # ==========================
        # 第4關
        # ==========================


        else:


            prompt=f"""

給予最後解析。

加入:
恭喜完成挑戰。

回答:

{msg}

"""


            data={

                "title":
                "🎉 挑戰完成",

                "summary":
                get_ai_response(prompt),

                "task":
                "輸入重新開始挑戰下一題"

            }



            reply=create_card(
                data,
                4
            )



            qr=quick_buttons(
                [
                    "重新開始"
                ]
            )





        reply.quick_reply=qr



        line_bot_api.reply_message(

            event.reply_token,

            reply

        )



    except Exception as e:


        print(
            e,
            file=sys.stderr
        )


        line_bot_api.reply_message(

            event.reply_token,

            TextSendMessage(

                text=
                "系統錯誤，請輸入重新開始"

            )

        )






if __name__=="__main__":

    app.run(
        host="0.0.0.0",
        port=5000
    )
