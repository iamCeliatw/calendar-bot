import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# 讀取行程 + 建立／修改／刪除事件
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# 本機預設 token.json；Cloud Run 可設為 Secret 掛載路徑，例如 /secrets/token.json
TOKEN_FILE = os.environ.get("GOOGLE_TOKEN_PATH", "token.json")


def _allow_browser_oauth() -> bool:
    """Cloud Run（K_SERVICE）與 CI 環境不應開本機瀏覽器授權。"""
    if os.environ.get("ALLOW_BROWSER_OAUTH", "").lower() in ("0", "false", "no"):
        return False
    if os.environ.get("K_SERVICE") or os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
        return False
    return True


def _persist_token(creds_json: str) -> None:
    """掛載唯讀 Secret 時略過寫入；程序內 refresh 仍有效。"""
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds_json)
    except OSError:
        pass


def _has_required_scopes(creds: Credentials) -> bool:
    """舊 token 可能仍是 calendar.readonly，刷新會出現 invalid_scope，須重新授權。"""
    if not creds.scopes:
        return False
    granted = set(creds.scopes)
    return all(s in granted for s in SCOPES)


def _run_oauth_flow() -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    return flow.run_local_server(port=0)


def get_credentials():
    """取得或刷新 Google OAuth 憑證"""
    creds = None

    if os.path.exists(TOKEN_FILE) and os.path.getsize(TOKEN_FILE) > 0:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if not _has_required_scopes(creds):
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                creds = None
                if os.path.exists(TOKEN_FILE):
                    try:
                        os.remove(TOKEN_FILE)
                    except OSError:
                        pass
        if not creds or not creds.valid:
            if not _allow_browser_oauth():
                raise RuntimeError(
                    "無法取得有效的 Google 憑證。\n"
                    "GitHub Actions：請確認 GOOGLE_TOKEN_JSON_B64 Secret 已設定且包含有效的 "
                    "refresh_token（重新在本機執行 OAuth 授權後，以 base64 重新編碼 token.json）。\n"
                    "Cloud Run：請掛載已授權的 token 並設定 GOOGLE_TOKEN_PATH 環境變數。"
                )
            creds = _run_oauth_flow()
        _persist_token(creds.to_json())

    return creds


def _parse_event(event: dict, tz: ZoneInfo) -> dict:
    """將 Google Calendar 事件解析成簡潔格式（含 event_id）。"""
    start = event["start"]
    end = event["end"]

    is_editable = event.get("eventType", "default") == "default"

    if "date" in start:
        return {
            "event_id": event.get("id", ""),
            "summary": event.get("summary", "（無標題）"),
            "start_time": None,
            "end_time": None,
            "is_all_day": True,
            "location": event.get("location", ""),
            "description": event.get("description", ""),
            "is_editable": is_editable,
        }

    start_dt = datetime.fromisoformat(start["dateTime"]).astimezone(tz)
    end_dt   = datetime.fromisoformat(end["dateTime"]).astimezone(tz)

    return {
        "event_id": event.get("id", ""),
        "summary": event.get("summary", "（無標題）"),
        "start_time": start_dt,
        "end_time": end_dt,
        "is_all_day": False,
        "location": event.get("location", ""),
        "description": event.get("description", ""),
        "is_editable": is_editable,
    }


def get_events(date: datetime, timezone_str: str = "Asia/Taipei") -> list[dict]:
    """取得指定日期的所有行程。"""
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)

    tz = ZoneInfo(timezone_str)
    start = datetime(date.year, date.month, date.day, 0, 0, 0, tzinfo=tz)
    end   = start + timedelta(days=1)

    result = service.events().list(
        calendarId="primary",
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    return [_parse_event(e, tz) for e in result.get("items", [])]


def get_events_for_days(
    start: datetime,
    end: datetime,
    timezone_str: str = "Asia/Taipei",
) -> dict[str, list[dict]]:
    """取得日期範圍內每天的行程，回傳 {YYYY-MM-DD: [events]} dict（用於週檢視）。"""
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)
    tz = ZoneInfo(timezone_str)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)

    result = service.events().list(
        calendarId="primary",
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events_by_day: dict[str, list[dict]] = {}
    current = start
    while current < end:
        events_by_day[current.strftime("%Y-%m-%d")] = []
        current += timedelta(days=1)

    for raw in result.get("items", []):
        parsed = _parse_event(raw, tz)
        if parsed["is_all_day"]:
            date_str = raw["start"].get("date", "")
        else:
            date_str = parsed["start_time"].strftime("%Y-%m-%d") if parsed["start_time"] else ""
        if date_str in events_by_day:
            events_by_day[date_str].append(parsed)

    return events_by_day


def get_events_in_range(
    start: datetime,
    end: datetime,
    timezone_str: str = "Asia/Taipei",
) -> list[dict]:
    """取得指定時間範圍內的行程（用於衝突偵測）。"""
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)

    tz = ZoneInfo(timezone_str)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)

    result = service.events().list(
        calendarId="primary",
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    return [_parse_event(e, tz) for e in result.get("items", [])]


def create_timed_event(
    summary: str,
    start: datetime,
    end: datetime,
    timezone_str: str = "Asia/Taipei",
    location: str = "",
) -> dict:
    """在 primary 日曆建立有起訖時間的事件，回傳 API 回應 body。"""
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)
    tz = ZoneInfo(timezone_str)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    body: dict = {
        "summary": summary,
        "start": {"dateTime": start.isoformat(), "timeZone": timezone_str},
        "end":   {"dateTime": end.isoformat(),   "timeZone": timezone_str},
    }
    if location:
        body["location"] = location
    return service.events().insert(calendarId="primary", body=body).execute()


def get_event(event_id: str) -> dict:
    """取得單一行程，回傳解析後的事件 dict。"""
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)
    raw = service.events().get(calendarId="primary", eventId=event_id).execute()
    tz = ZoneInfo("Asia/Taipei")
    return _parse_event(raw, tz)


def update_event(
    event_id: str,
    summary: str,
    start: datetime | None,
    end: datetime | None,
    timezone_str: str = "Asia/Taipei",
    location: str = "",
    is_all_day: bool = False,
    all_day_date: str = "",
) -> dict:
    """更新行程（patch），回傳更新後事件 dict。"""
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)
    existing = service.events().get(calendarId="primary", eventId=event_id).execute()
    if existing.get("eventType", "default") != "default":
        raise ValueError("此行程由 Gmail 自動建立（例如訂位、航班通知），無法在此編輯，請至 Google 日曆查看")
    body: dict = {"summary": summary}
    if is_all_day:
        body["start"] = {"date": all_day_date}
        body["end"]   = {"date": all_day_date}
    else:
        tz = ZoneInfo(timezone_str)
        if start and start.tzinfo is None:
            start = start.replace(tzinfo=tz)
        if end and end.tzinfo is None:
            end = end.replace(tzinfo=tz)
        body["start"] = {"dateTime": start.isoformat(), "timeZone": timezone_str}
        body["end"]   = {"dateTime": end.isoformat(),   "timeZone": timezone_str}
    if location is not None:
        body["location"] = location
    return service.events().patch(
        calendarId="primary", eventId=event_id, body=body
    ).execute()


def delete_event(event_id: str) -> None:
    """刪除行程。"""
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)
    service.events().delete(calendarId="primary", eventId=event_id).execute()


def create_all_day_event(
    summary: str,
    date_str: str,
    timezone_str: str = "Asia/Taipei",
    location: str = "",
) -> dict:
    """在 primary 日曆建立全天事件。date_str 格式為 'YYYY-MM-DD'。"""
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)
    body: dict = {
        "summary": summary,
        "start": {"date": date_str},
        "end":   {"date": date_str},
    }
    if location:
        body["location"] = location
    return service.events().insert(calendarId="primary", body=body).execute()


