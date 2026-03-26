import os
import time
from datetime import datetime, timezone

import psutil
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import SERVER_NAME, PROC_PATH
from app.monitor.system import get_total_ram, get_processes, get_cpu_avg, get_docker_container_count
from app.monitor.checks import run_all_checks, get_script_key
from app.storage.state import load_state, save_state

psutil.PROCFS_PATH = PROC_PATH

router = Router()

HELP_TEXT = """👋 Vector Server Monitor

Доступные команды:
/status — общая картина сервера
/top — топ 10 процессов по RAM
/top_cpu — топ 10 процессов по CPU
/ps <название> — найти процесс по имени
/alerts — проверить алерты прямо сейчас
/help — эта справка"""


def _fmt_mb(mb: float) -> str:
    if mb >= 1024:
        return f"{mb / 1024:.1f}GB"
    return f"{mb:.0f}MB"


def _time_ago(create_time: float) -> str:
    elapsed = time.time() - create_time
    if elapsed < 60:
        return f"~{int(elapsed)}с назад"
    elif elapsed < 3600:
        return f"~{int(elapsed // 60)}м назад"
    elif elapsed < 86400:
        return f"~{int(elapsed // 3600)}ч назад"
    else:
        return f"~{int(elapsed // 86400)}д назад"


@router.message(Command("start", "help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


@router.message(Command("status"))
async def cmd_status(message: Message):
    ram = get_total_ram()
    processes = get_processes()
    cpu_avg = get_cpu_avg()
    docker_count = get_docker_container_count()

    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    total_gb = ram["total_mb"] / 1024
    used_gb = ram["used_mb"] / 1024

    text = (
        f"📊 Сервер: {SERVER_NAME}\n"
        f"🕐 {now}\n\n"
        f"💾 RAM: {ram['used_percent']}% ({used_gb:.1f}GB / {total_gb:.0f}GB)\n"
        f"⚡ CPU: {cpu_avg}% (средняя)\n"
        f"🖥 Процессов: {len(processes)}\n"
        f"🐳 Docker контейнеров: {docker_count}"
    )
    await message.answer(text)


@router.message(Command("top"))
async def cmd_top(message: Message):
    processes = get_processes()
    top = sorted(processes, key=lambda p: p["mem_percent"], reverse=True)[:10]

    lines = ["💾 Топ процессов по RAM:\n"]
    for i, proc in enumerate(top, 1):
        lines.append(
            f"{i}. {proc['display_name']}\n"
            f"   PID {proc['pid']} | {proc['mem_percent']}% | {_fmt_mb(proc['mem_mb'])}\n"
        )

    await message.answer("\n".join(lines) if lines else "Нет данных")


@router.message(Command("top_cpu"))
async def cmd_top_cpu(message: Message):
    processes = get_processes()
    top = sorted(processes, key=lambda p: p["cpu_percent"], reverse=True)[:10]

    lines = ["⚡ Топ процессов по CPU:\n"]
    for i, proc in enumerate(top, 1):
        lines.append(
            f"{i}. {proc['display_name']}\n"
            f"   PID {proc['pid']} | CPU {proc['cpu_percent']}% | RAM {proc['mem_percent']}%\n"
        )

    await message.answer("\n".join(lines) if lines else "Нет данных")


@router.message(Command("ps"))
async def cmd_ps(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Использование: /ps <название процесса>")
        return

    query = args[1].strip().lower()
    processes = get_processes()
    found = [
        p for p in processes
        if query in p["display_name"].lower() or query in p["cmd"].lower()
    ]

    if not found:
        await message.answer(f'🔍 Поиск: "{query}"\n\nПроцессы не найдены.')
        return

    lines = [f'🔍 Поиск: "{query}"\n\nНайдено {len(found)} процесс(ов):\n']

    keys = [get_script_key(p) for p in found]
    has_duplicate = len(keys) != len(set(keys))

    for proc in found:
        create_time_str = ""
        try:
            p = psutil.Process(proc["pid"])
            create_time_str = _time_ago(p.create_time())
        except Exception:
            create_time_str = "неизвестно"

        lines.append(
            f"PID {proc['pid']} | {proc['display_name']}\n"
            f"RAM: {proc['mem_percent']}% ({_fmt_mb(proc['mem_mb'])}) | CPU: {proc['cpu_percent']}%\n"
            f"Пользователь: {proc['user']}\n"
            f"Запущен: {create_time_str}\n"
        )

    if has_duplicate:
        lines.append("⚠️ Обнаружен дубликат!")

    await message.answer("\n".join(lines))


@router.message(Command("alerts"))
async def cmd_alerts(message: Message):
    state = load_state()
    alerts = run_all_checks(state)
    save_state(state)

    if not alerts:
        ram = get_total_ram()
        processes = get_processes()
        cpu_avg = get_cpu_avg()
        text = f"✅ Всё в порядке\nRAM: {ram['used_percent']}% | CPU: {cpu_avg}%"
    else:
        text = "\n\n".join(alerts)

    await message.answer(text)
