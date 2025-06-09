import requests
from fastapi import FastAPI
from fastapi import Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, TextMessage, \
    ReplyMessageRequest
from linebot.v3.webhooks import MessageEvent, TextMessageContent

import utilities as utils
from room_manager import RoomManager

room_manager = RoomManager()

app = FastAPI()
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

config = utils.read_config()
configuration = Configuration(access_token=config['line_channel_access_token'])
handler = WebhookHandler(config['line_channel_secret'])


@app.post("/callback")
async def callback(request: Request):
    """Callback function for line webhook."""

    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = await request.body()

    # handle webhook body
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/channel secret.")
        raise HTTPException(status_code=400, detail="Invalid signature.")

    return 'OK'


def create_room_via_api(user_id: str, user_name: str):
    """Create a room via internal API call."""
    try:
        response = requests.post(
            f"http://localhost:{config['api_endpoints_port']}/api/room/create",
            params={"user_id": user_id, "user_name": user_name}
        )
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to create room: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error creating room: {e}")
        return None


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    with ApiClient(configuration) as api_client:
        if event.source.type == 'group':  # Exclude group messages, only process DM messages
            return
        line_bot_api = MessagingApi(api_client)
        message_received = event.message.text
        user_id = event.source.user_id

        # Handle commands messages
        if message_received == "創建房間":
            user_name = line_bot_api.get_profile(user_id).display_name
            room_data = create_room_via_api(user_id, user_name)

            if room_data:
                room_id = room_data['room_id']
                room_url = f"http://localhost:3000/room/{room_id}?userId={user_id}"
                reply_message = TextMessage(text=room_url)
            else:
                reply_message = TextMessage(text="建立房間時發生錯誤，請稍後再試。")

            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, messages=[reply_message]))


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=config['line_webhook_port'])
