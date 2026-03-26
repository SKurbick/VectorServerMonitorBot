from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from app.config import TELEGRAM_TOKEN

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
