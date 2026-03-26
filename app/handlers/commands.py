import os
import signal
import time

import psutil
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from app.config import SERVER_NAME, PROC_PATH, ADMIN_IDS
from app.monitor.system import (
    get_total_ram, get_processes, get_cpu_avg,
    get_docker_containers, get_docker_container_count,
    get_disk_usage, get_top_dirs, get_uptime_seconds,
    get_script_key, build_container_name_map,
)
from app.monitor.checks import run_all_checks
from app.storage.state import load_state, save_state
from app.utils import progress_bar, format_uptime, fmt_mb

psutil.PROCFS_PATH = PROC_PATH

router = Router()

HELP_TEXT = """👋 Vector Server Monitor

Доступные команды:
/status — общая картина сервера
/top — топ 10 процессов по RAM
/top_cpu — топ 10 процессов по CPU
/ps <название> — найти процесс по имени
/docker — статус Docker контейнеров
/disk — использование диска
/alerts — проверить алерты прямо сейчас
/kill <PID> — убить процесс (admin)
/help — эта справка"""


def container_status_icon(status: str) -> str:
    if status == "running":
        return "🟢"
    elif status in ("restarting", "created"):
        return "🟡"
    else:
        return "🔴"


@router.message(Command("start", "help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


@router.message(Command("status"))
async def cmd_status(message: Message):
    from datetime import datetime
    ram = get_total_ram()
    processes = get_processes()
    cpu_avg = get_cpu_avg()
    disk = get_disk_usage()
    uptime_sec = get_uptime_seconds()

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    total_gb = ram["total_mb"] / 1024
    used_gb = ram["used_mb"] / 1024

    # Docker container stats
    containers = get_docker_containers()
    if containers is not None:
        total_c = len(containers)
        running_c = sum(1 for c in containers if c["status"] == "running")
        problem_c = sum(1 for c in containers if c["status"] not in ("running", "created"))
        if problem_c > 0:
            docker_line = f"🐳 Контейнеров: {total_c} (🟢 {running_c} running, 🔴 {problem_c} проблемных)"
        else:
            docker_line = f"🐳 Контейнеров: {total_c} (🟢 {running_c} running)"
    else:
        count = get_docker_container_count()
        docker_line = f"🐳 Контейнеров: {count}"

    ram_bar = progress_bar(ram["used_percent"])
    cpu_bar = progress_bar(cpu_avg * 10 if cpu_avg <= 10 else 100)  # load avg to percent approx
    disk_bar = progress_bar(disk["percent"])

    text = (
        f"📊 Сервер: {SERVER_NAME}\n"
        f"🕐 {now}\n\n"
        f"💾 RAM:  {ram_bar}  {ram['used_percent']}% ({used_gb:.1f}GB / {total_gb:.0f}GB)\n"
        f"⚡ CPU:  {progress_bar(min(cpu_avg * 10, 100))}  {cpu_avg}%\n"
        f"💿 Disk: {disk_bar}  {disk['percent']}% ({disk['used_gb']}GB / {disk['total_gb']}GB)\n\n"
        f"{docker_line}\n"
        f"🔧 Процессов: {len(processes)}\n"
        f"⏱ Uptime: {format_uptime(uptime_sec)}"
    )
    await message.answer(text)


@router.message(Command("top"))
async def cmd_top(message: Message):
    processes = get_processes()
    top = sorted(processes, key=lambda p: p["mem_percent"], reverse=True)[:10]

    lines = ["💾 Топ процессов по RAM:\n"]
    for i, proc in enumerate(top, 1):
        uptime_str = ""
        try:
            p = psutil.Process(proc["pid"])
            uptime_str = f" | ⏱ {format_uptime(time.time() - p.create_time())}"
        except Exception:
            pass
        lines.append(
            f"{i}. {proc['display_name']}\n"
            f"   PID {proc['pid']} | {proc['mem_percent']}% | {fmt_mb(proc['mem_mb'])}{uptime_str}\n"
        )

    text = "\n".join(lines)
    if len(text) > 4096:
        text = text[:4090] + "\n..."
    await message.answer(text or "Нет данных")


@router.message(Command("top_cpu"))
async def cmd_top_cpu(message: Message):
    processes = get_processes()
    top = sorted(processes, key=lambda p: p["cpu_percent"], reverse=True)[:10]

    lines = ["⚡ Топ процессов по CPU:\n"]
    for i, proc in enumerate(top, 1):
        uptime_str = ""
        try:
            p = psutil.Process(proc["pid"])
            uptime_str = f" | ⏱ {format_uptime(time.time() - p.create_time())}"
        except Exception:
            pass
        lines.append(
            f"{i}. {proc['display_name']}\n"
            f"   PID {proc['pid']} | CPU {proc['cpu_percent']}% | RAM {proc['mem_percent']}%{uptime_str}\n"
        )

    text = "\n".join(lines)
    if len(text) > 4096:
        text = text[:4090] + "\n..."
    await message.answer(text or "Нет данных")


def _ps_worker_role(cmd: str) -> str:
    """Extracts the worker role from postgres-like process cmdline."""
    # "postgres: checkpointer " → "checkpointer"
    # "postgres: vector idle   " → "vector idle"
    if ": " in cmd:
        role = cmd.split(": ", 1)[1].strip()
        # Trim trailing spaces from roles like "vector idle   "
        role = " ".join(role.split())
        return role if role else "worker"
    return cmd.strip()


def _ps_grouped_output(found: list, container_map: dict) -> list:
    """
    Returns lines for grouped display when many worker-processes are found.
    Groups by parent PID: main process → its workers.
    """
    pid_set = {p["pid"] for p in found}
    all_procs_by_pid = {p["pid"]: p for p in found}

    # Identify main processes: ppid is NOT in found set
    mains = [p for p in found if p["ppid"] not in pid_set]
    # Workers: ppid IS a pid in found set
    workers_by_ppid: dict = {}
    for p in found:
        if p["ppid"] in pid_set:
            workers_by_ppid.setdefault(p["ppid"], []).append(p)

    # Ungrouped: no main found for them and not a main themselves
    main_pids = {p["pid"] for p in mains}
    ungrouped = [
        p for p in found
        if p["pid"] not in main_pids and p["ppid"] not in pid_set
    ]

    lines = []

    for main in mains:
        container_name = container_map.get(main["container_id"], "")
        container_str = f" | 🐳 {container_name}" if container_name else (
            f" | 🐳 {main['container_id']}" if main["container_id"] else ""
        )

        uptime_str = ""
        try:
            p = psutil.Process(main["pid"])
            uptime_str = f"⏱ {format_uptime(time.time() - p.create_time())}"
        except Exception:
            pass

        lines.append(
            f"🐘 PID {main['pid']} (main){container_str}\n"
            f"   RAM: {main['mem_percent']}% ({fmt_mb(main['mem_mb'])}) | CPU: {main['cpu_percent']}%"
            + (f" | {uptime_str}" if uptime_str else "")
        )

        workers = workers_by_ppid.get(main["pid"], [])
        if workers:
            total_ram_mb = sum(w["mem_mb"] for w in workers)
            total_ram_pct = round(sum(w["mem_percent"] for w in workers), 1)

            # Collect unique roles
            roles = []
            seen_roles = set()
            for w in workers:
                role = _ps_worker_role(w["cmd"])
                # Shorten connection roles like "user dbname [local] idle" → "user@dbname"
                if len(role) > 30:
                    role = role[:28] + "…"
                if role not in seen_roles:
                    seen_roles.add(role)
                    roles.append(role)

            lines.append(
                f"   Воркеров: {len(workers)} | RAM итого: {total_ram_pct}% ({fmt_mb(total_ram_mb)})\n"
                f"   Роли: {', '.join(roles[:8])}"
                + (" ..." if len(roles) > 8 else "")
            )
        lines.append("")

    if ungrouped:
        lines.append("Без группы:")
        for p in ungrouped:
            role = _ps_worker_role(p["cmd"]) if ":" in p["cmd"] else p["script_name"]
            uptime_str = ""
            try:
                proc = psutil.Process(p["pid"])
                uptime_str = f" | ⏱ {format_uptime(time.time() - proc.create_time())}"
            except Exception:
                pass
            lines.append(
                f"  PID {p['pid']} | {role} | RAM: {p['mem_percent']}% ({fmt_mb(p['mem_mb'])}){uptime_str}"
            )

    return lines


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

    # Resolve container names for all found processes
    container_ids = {p["container_id"] for p in found if p.get("container_id")}
    container_map = build_container_name_map(container_ids)

    # Use grouped display when many same-name workers are found (>= 5 results)
    pid_set = {p["pid"] for p in found}
    has_workers = any(p["ppid"] in pid_set for p in found)
    use_grouped = len(found) >= 5 and has_workers

    if use_grouped:
        header = f'🔍 Поиск: "{query}"\n\nНайдено {len(found)} процесс(ов):\n'
        body_lines = _ps_grouped_output(found, container_map)
        text = header + "\n".join(body_lines)
    else:
        keys = [get_script_key(p) for p in found]
        has_duplicate = len(keys) != len(set(keys))

        lines = [f'🔍 Поиск: "{query}"\n\nНайдено {len(found)} процесс(ов):\n']
        for proc in found:
            uptime_str = "неизвестно"
            try:
                p = psutil.Process(proc["pid"])
                uptime_str = format_uptime(time.time() - p.create_time())
            except Exception:
                pass

            container_name = container_map.get(proc.get("container_id", ""), "")
            container_str = f"\n🐳 {container_name}" if container_name else (
                f"\n🐳 {proc['container_id']}" if proc.get("container_id") else ""
            )
            cwd_str = proc["cwd"] if proc["cwd"] != "unknown" else ""
            cwd_line = f"\n📁 {cwd_str}" if cwd_str else ""

            lines.append(
                f"PID {proc['pid']} | {proc['script_name']}"
                f"{cwd_line}{container_str}\n"
                f"RAM: {proc['mem_percent']}% ({fmt_mb(proc['mem_mb'])}) | CPU: {proc['cpu_percent']}% | ⏱ {uptime_str}\n"
                f"Пользователь: {proc['user']}\n"
            )

        if has_duplicate:
            lines.append("⚠️ Обнаружен дубликат!")
        text = "\n".join(lines)

    if len(text) > 4096:
        text = text[:4090] + "\n..."

    # Inline kill buttons — only for admins, only for main/ungrouped processes
    kb = None
    if message.from_user and message.from_user.id in ADMIN_IDS and found:
        if use_grouped:
            # Only show kill buttons for main processes
            pid_set_found = {p["pid"] for p in found}
            kill_targets = [p for p in found if p["ppid"] not in pid_set_found][:10]
        else:
            kill_targets = found[:10]

        if kill_targets:
            buttons = [
                InlineKeyboardButton(
                    text=f"🔴 Убить PID {p['pid']}",
                    callback_data=f"kill:{p['pid']}",
                )
                for p in kill_targets
            ]
            rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
            kb = InlineKeyboardMarkup(inline_keyboard=rows)

    await message.answer(text, reply_markup=kb)


@router.message(Command("kill"))
async def cmd_kill(message: Message):
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 У вас нет прав для этой команды")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.answer("Использование: /kill <PID>")
        return

    pid = int(args[1].strip())
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            name = proc.name()
            mem_mb = proc.memory_info().rss / 1024 / 1024
            cpu_pct = proc.cpu_percent(interval=None)
            username = proc.username()
            uptime_str = format_uptime(time.time() - proc.create_time())

        ram = get_total_ram()
        mem_pct = round(mem_mb / ram["total_mb"] * 100, 1) if ram["total_mb"] > 0 else 0.0

        # Find display name from processes list
        processes = get_processes()
        display = next((p["display_name"] for p in processes if p["pid"] == pid), name)

        text = (
            f"⚠️ Вы хотите убить процесс?\n\n"
            f"{display}\n"
            f"PID {pid} | RAM {mem_pct}% ({fmt_mb(mem_mb)}) | CPU {cpu_pct}%\n"
            f"Пользователь: {username}\n"
            f"Запущен: {uptime_str} назад"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да, убить", callback_data=f"kill_confirm:{pid}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="kill_cancel"),
        ]])
        await message.answer(text, reply_markup=kb)
    except psutil.NoSuchProcess:
        await message.answer(f"❌ Процесс PID {pid} не найден")


@router.message(Command("docker"))
async def cmd_docker(message: Message):
    containers = get_docker_containers()

    if containers is None:
        await message.answer(
            "🐳 Docker недоступен\nПроверьте монтирование /var/run/docker.sock"
        )
        return

    total = len(containers)
    running = sum(1 for c in containers if c["status"] == "running")
    problems = [c for c in containers if c["status"] not in ("running",)]

    lines = [f"🐳 Docker контейнеры | {SERVER_NAME}\n"]
    for c in sorted(containers, key=lambda x: x["status"] != "running"):
        icon = container_status_icon(c["status"])
        lines.append(f"{icon} {c['name']}    {c['status']}")

    lines.append(f"\nВсего: {total} | 🟢 {running} running | 🔴 {len(problems)} проблемных")

    text = "\n".join(lines)
    if len(text) > 3800:
        # Truncate and add note
        trimmed = []
        for line in lines[:-1]:  # exclude summary
            if sum(len(l) for l in trimmed) + len(line) > 3600:
                remaining = len(lines) - len(trimmed) - 1
                trimmed.append(f"...и ещё {remaining} контейнеров")
                break
            trimmed.append(line)
        trimmed.append(lines[-1])  # re-add summary
        text = "\n".join(trimmed)

    # Restart buttons for problem containers — admins only
    kb = None
    if message.from_user and message.from_user.id in ADMIN_IDS and problems:
        buttons = [
            [InlineKeyboardButton(
                text=f"🔄 Restart {c['name']}",
                callback_data=f"restart:{c['name']}",
            )]
            for c in problems[:10]
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(text, reply_markup=kb)


@router.message(Command("disk"))
async def cmd_disk(message: Message):
    disk = get_disk_usage()
    partitions = get_top_dirs()

    bar = progress_bar(disk["percent"])

    lines = [
        f"💿 Диск | {SERVER_NAME}\n",
        f"Раздел /",
        f"Всего:    {disk['total_gb']} GB",
        f"Занято:   {disk['used_gb']} GB  {bar}  {disk['percent']}%",
        f"Свободно: {disk['free_gb']} GB",
    ]

    if partitions:
        lines.append("\n📁 Разделы по использованию:")
        for i, p in enumerate(partitions, 1):
            p_bar = progress_bar(p["percent"])
            lines.append(
                f"{i}. {p['path']}    {p['used_gb']} GB / {p['total_gb']} GB  {p_bar}  {p['percent']}%"
            )

    await message.answer("\n".join(lines))


@router.message(Command("alerts"))
async def cmd_alerts(message: Message):
    state = load_state()
    alerts = run_all_checks(state)
    save_state(state)

    if not alerts:
        ram = get_total_ram()
        cpu_avg = get_cpu_avg()
        text = f"✅ Всё в порядке\nRAM: {ram['used_percent']}% | CPU: {cpu_avg}%"
    else:
        text = "\n\n".join(alerts)
        if len(text) > 4096:
            text = text[:4090] + "\n..."

    await message.answer(text)
