import asyncio
from aiogram.types import BotCommand
from app.bot import bot, dp
from app.scheduler import start_scheduler
from app.handlers.commands import router as commands_router
from app.handlers.callbacks import router as callbacks_router


async def set_commands():
    commands = [
        BotCommand(command="status",  description="📊 Общая картина сервера"),
        BotCommand(command="top",     description="💾 Топ процессов по RAM"),
        BotCommand(command="top_cpu", description="⚡ Топ процессов по CPU"),
        BotCommand(command="ps",      description="🔍 Найти процесс по имени"),
        BotCommand(command="docker",  description="🐳 Статус контейнеров"),
        BotCommand(command="disk",    description="💿 Использование диска"),
        BotCommand(command="alerts",  description="🚨 Проверить алерты сейчас"),
        BotCommand(command="kill",    description="🔴 Убить процесс (admin)"),
        BotCommand(command="help",    description="📖 Справка"),
    ]
    await bot.set_my_commands(commands)


async def main():
    dp.include_router(commands_router)
    dp.include_router(callbacks_router)
    await set_commands()
    await start_scheduler()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
