from app.monitor.system import get_total_ram, get_processes, get_script_key
from app.storage.state import should_alert, load_state, save_state
from app.config import (
    RAM_PROCESS_WARN, RAM_PROCESS_CRIT,
    RAM_TOTAL_WARN, RAM_TOTAL_CRIT,
    CPU_PROCESS_WARN, CPU_PROCESS_CRIT,
    REPEAT_ALERT_MIN,
)

DUPLICATE_WHITELIST = [
    "celery",
    "nginx: worker",
    "containerd-shim",
    "python -c",
    "python3 -c",
    "spawn_main",
    "postgres:",
    "gunicorn",
    "uvicorn",
]


def _is_whitelisted(process: dict) -> bool:
    cmd = process.get("cmd", "").lower()
    name = process.get("script_name", "").lower()
    for pattern in DUPLICATE_WHITELIST:
        if pattern.lower() in cmd or pattern.lower() in name:
            return True
    return False


def _fmt_mb(mb: float) -> str:
    if mb >= 1024:
        return f"{mb / 1024:.1f}GB"
    return f"{mb:.0f}MB"


def check_total_ram(ram: dict, state: dict) -> list:
    alerts = []
    pct = ram["used_percent"]
    used_mb = ram["used_mb"]
    total_mb = ram["total_mb"]

    if pct >= RAM_TOTAL_CRIT:
        key = "ram_total_crit"
        if should_alert(state, key, REPEAT_ALERT_MIN):
            alerts.append(
                f"🔴 Критично: общая RAM {pct}% ({_fmt_mb(used_mb)} / {_fmt_mb(total_mb)})"
            )
    elif pct >= RAM_TOTAL_WARN:
        key = "ram_total_warn"
        if should_alert(state, key, REPEAT_ALERT_MIN):
            alerts.append(
                f"🟡 Высокое потребление RAM: {pct}% ({_fmt_mb(used_mb)} / {_fmt_mb(total_mb)})"
            )

    return alerts


def check_process_ram(processes: list, state: dict) -> list:
    alerts = []
    for proc in processes:
        if _is_whitelisted(proc):
            continue
        pct = proc["mem_percent"]
        name = proc["display_name"]
        pid = proc["pid"]
        mem_mb = proc["mem_mb"]

        if pct >= RAM_PROCESS_CRIT:
            key = f"ram_proc_crit_{proc['script_name']}_{proc['cwd']}"
            if should_alert(state, key, REPEAT_ALERT_MIN):
                alerts.append(
                    f"🔴 Критично RAM процесса:\n{name}\nPID {pid}: {pct}% RAM ({_fmt_mb(mem_mb)})"
                )
        elif pct >= RAM_PROCESS_WARN:
            key = f"ram_proc_warn_{proc['script_name']}_{proc['cwd']}"
            if should_alert(state, key, REPEAT_ALERT_MIN):
                alerts.append(
                    f"🟡 Высокое потребление RAM:\n{name}\nPID {pid}: {pct}% RAM ({_fmt_mb(mem_mb)})"
                )

    return alerts


def check_duplicates(processes: list, state: dict) -> list:
    alerts = []
    groups: dict = {}

    for proc in processes:
        if _is_whitelisted(proc):
            continue
        key = get_script_key(proc)
        if not key.startswith("::"):
            groups.setdefault(key, []).append(proc)

    for script_key, procs in groups.items():
        if len(procs) < 2:
            continue

        alert_key = f"dup_{script_key}"
        if not should_alert(state, alert_key, REPEAT_ALERT_MIN):
            continue

        name = procs[0]["display_name"]
        total_mem_mb = sum(p["mem_mb"] for p in procs)
        total_pct = sum(p["mem_percent"] for p in procs)

        lines = [f"🔴 Дубликат процесса:\n{name} — {len(procs)} экземпляра"]
        for p in procs:
            lines.append(f"  PID {p['pid']}: {p['mem_percent']}% RAM ({_fmt_mb(p['mem_mb'])})")
        lines.append(f"  Итого: {round(total_pct, 1)}% RAM ({_fmt_mb(total_mem_mb)})")

        alerts.append("\n".join(lines))

    return alerts


def check_process_cpu(processes: list, state: dict) -> list:
    alerts = []
    for proc in processes:
        if _is_whitelisted(proc):
            continue
        pct = proc["cpu_percent"]
        name = proc["display_name"]
        pid = proc["pid"]

        if pct >= CPU_PROCESS_CRIT:
            key = f"cpu_proc_crit_{proc['script_name']}_{proc['cwd']}"
            if should_alert(state, key, REPEAT_ALERT_MIN):
                alerts.append(
                    f"🔴 Критично CPU процесса:\n{name}\nPID {pid}: CPU {pct}%"
                )
        elif pct >= CPU_PROCESS_WARN:
            key = f"cpu_proc_warn_{proc['script_name']}_{proc['cwd']}"
            if should_alert(state, key, REPEAT_ALERT_MIN):
                alerts.append(
                    f"🟡 Высокая нагрузка CPU:\n{name}\nPID {pid}: CPU {pct}%"
                )

    return alerts


def run_all_checks(state: dict) -> list:
    ram = get_total_ram()
    processes = get_processes()

    alerts = []
    alerts.extend(check_total_ram(ram, state))
    alerts.extend(check_process_ram(processes, state))
    alerts.extend(check_duplicates(processes, state))
    alerts.extend(check_process_cpu(processes, state))

    return alerts
