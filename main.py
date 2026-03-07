import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
import calendar_service
import line_service

load_dotenv()

TIMEZONE = os.getenv("TIMEZONE", "Asia/Taipei")
NOTIFY_HOUR = int(os.getenv("NOTIFY_HOUR", "8"))
NOTIFY_MINUTE = int(os.getenv("NOTIFY_MINUTE", "0"))
ENABLE_TOMORROW = os.getenv("ENABLE_TOMORROW_PREVIEW", "true").lower() == "true"


def notify():
    """主要通知邏輯，每天定時執行"""
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    today = now
    tomorrow = now + timedelta(days=1)

    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 開始讀取行程...")

    # 今日通知
    today_events = calendar_service.get_events(today, TIMEZONE)
    line_service.send_today_notification(today_events, today)

    # 明日預告
    if ENABLE_TOMORROW:
        tomorrow_events = calendar_service.get_events(tomorrow, TIMEZONE)
        line_service.send_tomorrow_notification(tomorrow_events, tomorrow)


def run_scheduler():
    """啟動排程器，每天固定時間執行"""
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        notify,
        trigger="cron",
        hour=NOTIFY_HOUR,
        minute=NOTIFY_MINUTE,
    )
    print(f"排程已啟動，每天 {NOTIFY_HOUR:02d}:{NOTIFY_MINUTE:02d} 發送通知")
    print("按 Ctrl+C 停止")
    scheduler.start()


if __name__ == "__main__":
    import sys

    # 支援立即測試：python main.py test
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("執行測試通知...")
        notify()
    else:
        run_scheduler()
