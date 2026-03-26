import os
import psutil
from app.config import PROC_PATH

psutil.PROCFS_PATH = PROC_PATH


def get_total_ram() -> dict:
    meminfo_path = os.path.join(PROC_PATH, "meminfo")
    data = {}
    try:
        with open(meminfo_path, "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    value_kb = int(parts[1])
                    data[key] = value_kb
    except Exception:
        return {"total_mb": 0, "used_mb": 0, "available_mb": 0, "used_percent": 0.0}

    total_kb = data.get("MemTotal", 0)
    available_kb = data.get("MemAvailable", 0)
    used_kb = total_kb - available_kb

    total_mb = total_kb / 1024
    used_mb = used_kb / 1024
    available_mb = available_kb / 1024
    used_percent = (used_kb / total_kb * 100) if total_kb > 0 else 0.0

    return {
        "total_mb": round(total_mb, 1),
        "used_mb": round(used_mb, 1),
        "available_mb": round(available_mb, 1),
        "used_percent": round(used_percent, 1),
    }


def _read_cmdline(pid: int) -> str:
    try:
        with open(f"{PROC_PATH}/{pid}/cmdline", "rb") as f:
            return f.read().decode("utf-8", errors="replace").replace("\x00", " ").strip()
    except Exception:
        return ""


def _read_cwd(pid: int) -> str:
    try:
        return os.readlink(f"{PROC_PATH}/{pid}/cwd")
    except Exception:
        return "unknown"


def _read_status_field(pid: int, field: str) -> str:
    try:
        with open(f"{PROC_PATH}/{pid}/status", "r") as f:
            for line in f:
                if line.startswith(field + ":"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def _build_display_name(script_name: str, cwd: str, cmd_parts: list) -> str:
    if cwd and cwd != "unknown":
        cwd_last = os.path.basename(cwd.rstrip("/"))
    else:
        cwd_last = ""

    # Check for first argument (not the interpreter or script itself)
    first_arg = ""
    if len(cmd_parts) > 1:
        # cmd_parts[0] is interpreter or script, find the script index
        # Typical: ["python", "script.py", "arg1"] or ["./script.py", "arg1"]
        script_idx = -1
        for i, part in enumerate(cmd_parts):
            if part == script_name or part.endswith("/" + script_name):
                script_idx = i
                break
        if script_idx >= 0 and script_idx + 1 < len(cmd_parts):
            candidate = cmd_parts[script_idx + 1]
            if candidate and not candidate.startswith("-"):
                first_arg = candidate

    if first_arg and cwd_last:
        return f"{script_name} [{first_arg}] ({cwd_last})"
    elif cwd_last:
        return f"{script_name} ({cwd_last})"
    else:
        return script_name


def get_script_key(process: dict) -> str:
    script_name = process.get("script_name", "")
    cwd = process.get("cwd", "")
    cmd = process.get("cmd", "")

    first_arg = ""
    cmd_parts = cmd.split()
    script_idx = -1
    for i, part in enumerate(cmd_parts):
        if part == script_name or part.endswith("/" + script_name):
            script_idx = i
            break
    if script_idx >= 0 and script_idx + 1 < len(cmd_parts):
        candidate = cmd_parts[script_idx + 1]
        if candidate and not candidate.startswith("-"):
            first_arg = candidate

    return f"{script_name}::{cwd}::{first_arg}"


def get_processes() -> list:
    try:
        mem_info = get_total_ram()
        total_mb = mem_info["total_mb"]
    except Exception:
        total_mb = 1

    result = []
    try:
        pids = [
            int(d) for d in os.listdir(PROC_PATH) if d.isdigit()
        ]
    except Exception:
        return result

    for pid in pids:
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                try:
                    mem_info_proc = proc.memory_info()
                    mem_mb = mem_info_proc.rss / 1024 / 1024
                except Exception:
                    mem_mb = 0

                try:
                    cpu_percent = proc.cpu_percent(interval=None)
                except Exception:
                    cpu_percent = 0.0

                try:
                    username = proc.username()
                except Exception:
                    username = "unknown"

            cmd = _read_cmdline(pid)
            cwd = _read_cwd(pid)

            if not cmd:
                continue

            cmd_parts = cmd.split()
            script_name = ""

            # Determine script name from cmdline
            for part in cmd_parts:
                if part.endswith(".py") or (
                    not part.startswith("-") and "/" in part and not part.startswith("/usr") and not part.startswith("/bin")
                ):
                    script_name = os.path.basename(part)
                    break
            if not script_name:
                script_name = os.path.basename(cmd_parts[0]) if cmd_parts else ""

            mem_percent = (mem_mb / total_mb * 100) if total_mb > 0 else 0.0

            display_name = _build_display_name(script_name, cwd, cmd_parts)

            result.append({
                "pid": pid,
                "user": username,
                "cpu_percent": round(cpu_percent, 1),
                "mem_percent": round(mem_percent, 1),
                "mem_mb": round(mem_mb, 1),
                "cmd": cmd,
                "cwd": cwd,
                "script_name": script_name,
                "display_name": display_name,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            continue
        except Exception:
            continue

    return result


def get_cpu_avg() -> float:
    try:
        with open(f"{PROC_PATH}/loadavg", "r") as f:
            content = f.read().split()
            if content:
                return float(content[0])
    except Exception:
        pass
    return 0.0


def get_docker_container_count() -> int:
    try:
        count = 0
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                cmdline = p.cmdline()
                name = p.name()
                if "containerd-shim" in name or (cmdline and "containerd-shim" in " ".join(cmdline)):
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return count
    except Exception:
        return 0
