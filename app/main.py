import asyncio
from app.bot import bot, dp
from app.scheduler import start_scheduler
from app.handlers.commands import router


async def main():
    dp.include_router(router)
    await start_scheduler()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
