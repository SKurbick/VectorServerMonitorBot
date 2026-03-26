import os
import signal

import psutil
from aiogram import Router, F
from aiogram.types import CallbackQuery

from app.config import ADMIN_IDS, PROC_PATH
from app.utils import fmt_mb, format_uptime
import time

psutil.PROCFS_PATH = PROC_PATH

router = Router()


@router.callback_query(F.data.startswith("kill:"))
async def handle_kill_request(callback: CallbackQuery):
    """Show confirmation dialog for killing a process."""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Нет прав", show_alert=True)
        return

    pid = int(callback.data.split(":")[1])
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            name = proc.name()
            mem_mb = proc.memory_info().rss / 1024 / 1024
            mem_pct = 0.0
            cpu_pct = proc.cpu_percent(interval=None)
            username = proc.username()
            uptime = format_uptime(time.time() - proc.create_time())

        from app.monitor.system import get_total_ram
        ram = get_total_ram()
        if ram["total_mb"] > 0:
            mem_pct = round(mem_mb / ram["total_mb"] * 100, 1)

        text = (
            f"⚠️ Вы хотите убить процесс?\n\n"
            f"{name}\n"
            f"PID {pid} | RAM {mem_pct}% ({fmt_mb(mem_mb)}) | CPU {cpu_pct}%\n"
            f"Пользователь: {username}\n"
            f"Запущен: {uptime} назад"
        )

        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да, убить", callback_data=f"kill_confirm:{pid}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="kill_cancel"),
        ]])
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
    except psutil.NoSuchProcess:
        await callback.answer(f"❌ Процесс PID {pid} не найден", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@router.callback_query(F.data.startswith("kill_confirm:"))
async def handle_kill_confirm(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Нет прав", show_alert=True)
        return

    pid = int(callback.data.split(":")[1])
    try:
        proc = psutil.Process(pid)
        name = proc.name()
        os.kill(pid, signal.SIGTERM)
        await callback.message.edit_text(
            f"✅ Процесс PID {pid} убит\n{name}",
            reply_markup=None,
        )
        await callback.answer()
    except psutil.NoSuchProcess:
        await callback.message.edit_text(
            f"❌ Процесс PID {pid} не найден",
            reply_markup=None,
        )
        await callback.answer()
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@router.callback_query(F.data == "kill_cancel")
async def handle_kill_cancel(callback: CallbackQuery):
    await callback.message.edit_text("❌ Отменено", reply_markup=None)
    await callback.answer()


@router.callback_query(F.data.startswith("restart:"))
async def handle_restart(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Нет прав", show_alert=True)
        return

    container_name = callback.data.split(":", 1)[1]
    try:
        import docker
        client = docker.from_env()
        container = client.containers.get(container_name)
        container.restart()
        await callback.answer(f"✅ Контейнер {container_name} перезапущен", show_alert=True)
        # Refresh the docker list message
        await callback.message.edit_text(
            f"✅ Контейнер <b>{container_name}</b> перезапускается...",
            reply_markup=None,
        )
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
