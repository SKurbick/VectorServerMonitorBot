from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot import bot
from app.config import CHECK_INTERVAL_MIN, TELEGRAM_CHAT_ID, SERVER_NAME
from app.monitor.checks import run_all_checks
from app.storage.state import load_state, save_state


async def _check_and_alert():
    state = load_state()
    alerts = run_all_checks(state)
    save_state(state)

    if not alerts:
        return

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    header = f"⚠️ СЕРВЕР {SERVER_NAME} | {now}\n"
    body = "\n\n".join(alerts)
    text = header + "\n" + body

    # Telegram message limit is 4096 chars
    if len(text) > 4096:
        text = text[:4090] + "\n..."

    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)


async def start_scheduler():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _check_and_alert,
        trigger="interval",
        minutes=CHECK_INTERVAL_MIN,
        id="monitor_check",
        replace_existing=True,
    )
    scheduler.start()
