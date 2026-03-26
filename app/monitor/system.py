import os
import subprocess
import time
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


def _parse_script_and_arg(cmd: str) -> tuple:
    """Returns (script_name, first_arg) parsed from cmdline string."""
    parts = cmd.split()
    script_name = None
    first_arg = ""
    for i, part in enumerate(parts):
        if "python" in part.lower():
            continue
        if part.startswith("-"):
            continue
        if script_name is None:
            script_name = os.path.basename(part)
            if i + 1 < len(parts) and not parts[i + 1].startswith("-"):
                first_arg = parts[i + 1]
            break
    if not script_name:
        script_name = parts[0] if parts else "unknown"
    return script_name, first_arg


def get_display_name(process: dict) -> str:
    cmd = process.get("cmd", "")
    cwd = process.get("cwd", "unknown")
    script_name, first_arg = _parse_script_and_arg(cmd)
    cwd_last = os.path.basename(cwd) if cwd != "unknown" else ""
    name = script_name
    if first_arg:
        name += f" [{first_arg}]"
    if cwd_last:
        name += f" ({cwd_last})"
    return name


def get_script_key(process: dict) -> str:
    cmd = process.get("cmd", "")
    cwd = process.get("cwd", "unknown")
    script_name, first_arg = _parse_script_and_arg(cmd)
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

            mem_percent = (mem_mb / total_mb * 100) if total_mb > 0 else 0.0

            proc_dict = {
                "pid": pid,
                "user": username,
                "cpu_percent": round(cpu_percent, 1),
                "mem_percent": round(mem_percent, 1),
                "mem_mb": round(mem_mb, 1),
                "cmd": cmd,
                "cwd": cwd,
            }
            script_name, _ = _parse_script_and_arg(cmd)
            proc_dict["script_name"] = script_name
            proc_dict["display_name"] = get_display_name(proc_dict)

            result.append(proc_dict)
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


def get_docker_containers() -> list:
    """Returns list of container dicts via Docker SDK. Returns None if Docker unavailable."""
    try:
        import docker
        client = docker.from_env()
        containers = client.containers.list(all=True)
        result = []
        for c in containers:
            result.append({
                "name": c.name,
                "status": c.status,
                "short_id": c.short_id,
            })
        return result
    except Exception:
        return None


def get_disk_usage() -> dict:
    usage = psutil.disk_usage("/")
    return {
        "total_gb": round(usage.total / 1024 ** 3, 1),
        "used_gb": round(usage.used / 1024 ** 3, 1),
        "free_gb": round(usage.free / 1024 ** 3, 1),
        "percent": usage.percent,
    }


def get_top_dirs() -> list:
    dirs = ["/var/lib/docker", "/home", "/opt", "/var", "/usr", "/tmp"]
    result = []
    for d in dirs:
        try:
            out = subprocess.check_output(
                ["du", "-sb", d],
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).decode()
            size_bytes = int(out.split()[0])
            result.append({
                "path": d,
                "size_gb": round(size_bytes / 1024 ** 3, 1),
            })
        except Exception:
            continue
    return sorted(result, key=lambda x: x["size_gb"], reverse=True)


def get_uptime_seconds() -> float:
    try:
        with open(f"{PROC_PATH}/uptime", "r") as f:
            return float(f.read().split()[0])
    except Exception:
        try:
            return time.time() - psutil.boot_time()
        except Exception:
            return 0.0
