# get_user_id_login.py
# 用 LINE Login OAuth 取得 User ID，不需要 webhook 或 ngrok
# 需要先在 LINE Developers 建立 LINE Login channel

import os
import webbrowser
import secrets
import urllib.parse
import urllib.request
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

load_dotenv()

LINE_LOGIN_CHANNEL_ID = os.environ["LINE_LOGIN_CHANNEL_ID"]
LINE_LOGIN_CHANNEL_SECRET = os.environ["LINE_LOGIN_CHANNEL_SECRET"]
REDIRECT_URI = "http://localhost:8080/callback"

received_code = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global received_code
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        received_code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("<h2>取得成功！請回到終端機查看 User ID</h2>".encode())

    def log_message(self, format, *args):
        pass  # 關掉 log 輸出


def get_user_id():
    state = secrets.token_urlsafe(16)

    # Step 1: 產生 LINE Login URL
    auth_url = "https://access.line.me/oauth2/v2.1/authorize?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": LINE_LOGIN_CHANNEL_ID,
            "redirect_uri": REDIRECT_URI,
            "state": state,
            "scope": "profile openid",
        }
    )

    print("開啟瀏覽器進行 LINE 登入...")
    webbrowser.open(auth_url)

    # Step 2: 啟動本機暫時伺服器等待 callback
    print("等待授權回應（本機 port 8080）...")
    server = HTTPServer(("localhost", 8080), CallbackHandler)
    server.handle_request()  # 只處理一次就停止

    if not received_code:
        print("❌ 未收到授權碼")
        return

    # Step 3: 用 code 換 access_token
    token_data = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": received_code,
            "redirect_uri": REDIRECT_URI,
            "client_id": LINE_LOGIN_CHANNEL_ID,
            "client_secret": LINE_LOGIN_CHANNEL_SECRET,
        }
    ).encode()

    req = urllib.request.Request(
        "https://api.line.me/oauth2/v2.1/token",
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as res:
        token_info = json.loads(res.read())

    access_token = token_info["access_token"]

    # Step 4: 呼叫 Profile API 取得 User ID
    req = urllib.request.Request(
        "https://api.line.me/v2/profile",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req) as res:
        profile = json.loads(res.read())

    print(f"\n✅ 顯示名稱：{profile['displayName']}")
    print(f"✅ User ID：{profile['userId']}")
    print(f"\n請將以下內容加入 .env：")
    print(f"LINE_USER_IDS={profile['userId']}")


if __name__ == "__main__":
    get_user_id()
