import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def get_credentials():
    """取得或刷新 Google OAuth 憑證"""
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return creds


def get_events(date: datetime, timezone_str: str = "Asia/Taipei") -> list[dict]:
    """取得指定日期的所有行程"""
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)

    tz = ZoneInfo(timezone_str)
    start = datetime(date.year, date.month, date.day, 0, 0, 0, tzinfo=tz)
    end = start + timedelta(days=1)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    raw_events = events_result.get("items", [])
    return [_parse_event(e, tz) for e in raw_events]


def _parse_event(event: dict, tz: ZoneInfo) -> dict:
    """將 Google Calendar 事件解析成簡潔格式"""
    start = event["start"]
    end = event["end"]

    # 全天事件
    if "date" in start:
        return {
            "summary": event.get("summary", "（無標題）"),
            "start_time": None,
            "end_time": None,
            "is_all_day": True,
            "location": event.get("location", ""),
            "description": event.get("description", ""),
        }

    # 有時間的事件
    start_dt = datetime.fromisoformat(start["dateTime"]).astimezone(tz)
    end_dt = datetime.fromisoformat(end["dateTime"]).astimezone(tz)

    return {
        "summary": event.get("summary", "（無標題）"),
        "start_time": start_dt,
        "end_time": end_dt,
        "is_all_day": False,
        "location": event.get("location", ""),
        "description": event.get("description", ""),
    }
