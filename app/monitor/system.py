import os
import re
import subprocess
import time
import psutil
from app.config import PROC_PATH


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
    """
    Читает реальный рабочий каталог процесса.

    Для процессов хоста — читает напрямую из /proc/<pid>/cwd.
    Для процессов внутри Docker-контейнеров — получает имя контейнера
    через cgroup и Docker API.
    """
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except PermissionError:
        return _get_container_name_from_cgroup(pid)
    except Exception:
        return "unknown"


def _get_container_name_from_cgroup(pid: int) -> str:
    """
    Извлекает имя Docker-контейнера из cgroup файла процесса.

    Пример строки в /proc/<pid>/cgroup:
    0::/system.slice/docker-aa77ce97eeb619d4edcc47e804df8988cbfb3016040be450a39e14c8093601f9.scope

    Возвращает строку вида "[docker] vector_project_container"
    или "container" если не удалось определить имя.
    """
    try:
        with open(f"/proc/{pid}/cgroup", "r") as f:
            content = f.read()

        match = re.search(r"docker-([a-f0-9]{12,64})\.scope", content)
        if not match:
            return "container"

        container_id = match.group(1)

        result = subprocess.run(
            ["/usr/bin/docker", "inspect", "--format", "{{.Name}}", container_id],
            capture_output=True,
            text=True,
            timeout=3
        )
        if result.returncode == 0:
            name = result.stdout.strip().lstrip("/")
            return f"[docker] {name}"

        return "container"

    except Exception:
        return "container"


def _read_status_field(pid: int, field: str) -> str:
    try:
        with open(f"{PROC_PATH}/{pid}/status", "r") as f:
            for line in f:
                if line.startswith(field + ":"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def _resolve_username(pid: int, uid: str) -> str:
    """
    Resolves a numeric UID to a username.
    First tries the container's own /proc/<pid>/root/etc/passwd,
    then falls back to returning the raw UID string.
    """
    if not uid.isdigit():
        return uid  # already resolved by psutil
    try:
        passwd_path = f"{PROC_PATH}/{pid}/root/etc/passwd"
        with open(passwd_path, "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) >= 3 and parts[2] == uid:
                    return parts[0]
    except Exception:
        pass
    return uid


def _read_ppid(pid: int) -> int:
    val = _read_status_field(pid, "PPid")
    try:
        return int(val)
    except Exception:
        return 0


def _read_container_id(pid: int) -> str:
    """Reads Docker container ID from /proc/<pid>/cgroup (supports v1 and v2)."""
    try:
        with open(f"{PROC_PATH}/{pid}/cgroup", "r") as f:
            for line in f:
                # cgroup v1: 12:memory:/docker/<id>
                if "/docker/" in line:
                    part = line.split("/docker/")[-1].strip()
                    cid = part.split("/")[0]
                    if len(cid) >= 12:
                        return cid[:12]
                # cgroup v2: 0::/system.slice/docker-<id>.scope
                if "docker-" in line and ".scope" in line:
                    part = line.split("docker-")[-1].split(".scope")[0].strip()
                    if len(part) >= 12:
                        return part[:12]
    except Exception:
        pass
    return ""


def build_container_name_map(container_ids: set) -> dict:
    """Returns {short_id: container_name} for given container IDs via Docker SDK."""
    if not container_ids:
        return {}
    try:
        import docker
        client = docker.from_env()
        result = {}
        for c in client.containers.list(all=True):
            if c.short_id in container_ids:
                result[c.short_id] = c.name
        return result
    except Exception:
        return {}


def _parse_python_cmd(cmd: str) -> tuple:
    """
    Парсит команду Python и возвращает (script_name, first_arg).

    Обрабатывает форматы:
      python script.py arg1          -> ("script.py", "arg1")
      python -m module.name arg1     -> ("module.name", "arg1")
      python /full/path/script.py    -> ("script.py", "")
    """
    parts = cmd.split()
    script_name = None
    first_arg = ""
    i = 0

    while i < len(parts):
        part = parts[i]

        # Пропускаем интерпретатор python
        if "python" in part.lower() and (
            part.endswith("python")
            or part.endswith("python3")
            or "python3." in part
            or "python2." in part
        ):
            i += 1
            continue

        # Флаг -m: следующий элемент — имя модуля
        if part == "-m":
            if i + 1 < len(parts):
                script_name = parts[i + 1]
                if i + 2 < len(parts) and not parts[i + 2].startswith("-"):
                    first_arg = parts[i + 2]
            break

        # Пропускаем прочие флаги (-u, -W, -O и т.д.)
        if part.startswith("-"):
            i += 1
            continue

        # Первое оставшееся — скрипт
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
    script_name, first_arg = _parse_python_cmd(cmd)
    cwd_last = os.path.basename(cwd) if cwd not in ("unknown", "/") else cwd
    name = script_name
    if first_arg:
        name += f" [{first_arg}]"
    if cwd_last:
        name += f" ({cwd_last})"
    return name


def get_script_key(process: dict) -> str:
    cmd = process.get("cmd", "")
    cwd = process.get("cwd", "unknown")
    script_name, first_arg = _parse_python_cmd(cmd)
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
                    username = str(proc.uids().real) if hasattr(proc, "uids") else "unknown"

            cmd = _read_cmdline(pid)
            cwd = _read_cwd(pid)

            if not cmd:
                continue

            mem_percent = (mem_mb / total_mb * 100) if total_mb > 0 else 0.0

            username = _resolve_username(pid, username)

            proc_dict = {
                "pid": pid,
                "user": username,
                "cpu_percent": round(cpu_percent, 1),
                "mem_percent": round(mem_percent, 1),
                "mem_mb": round(mem_mb, 1),
                "cmd": cmd,
                "cwd": cwd,
                "ppid": _read_ppid(pid),
                "container_id": _read_container_id(pid),
            }
            script_name, _ = _parse_python_cmd(cmd)
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


def get_top_dirs() -> list[dict]:
    """
    Читает смонтированные разделы через /proc/mounts
    и считает размер каждого через os.statvfs().
    Не требует прав доступа к содержимому папок.
    """
    result = []
    seen_devices = set()

    SKIP_FS_TYPES = {
        "tmpfs", "devtmpfs", "sysfs", "proc", "cgroup", "cgroup2",
        "devpts", "mqueue", "hugetlbfs", "debugfs", "tracefs",
        "securityfs", "configfs", "fusectl", "overlay", "none",
        "nsfs", "bpf", "pstore", "autofs"
    }

    try:
        with open("/proc/mounts", "r") as f:
            mounts = f.readlines()
    except Exception:
        return []

    for line in mounts:
        parts = line.split()
        if len(parts) < 3:
            continue

        device = parts[0]
        mount_point = parts[1]
        fs_type = parts[2]

        if fs_type in SKIP_FS_TYPES:
            continue
        if mount_point.startswith("/sys"):
            continue
        if mount_point.startswith("/proc"):
            continue
        if mount_point.startswith("/dev/") or mount_point == "/dev":
            continue
        if mount_point.startswith("/run/"):
            continue

        if device in seen_devices:
            continue
        seen_devices.add(device)

        try:
            stat = os.statvfs(mount_point)
            total_bytes = stat.f_blocks * stat.f_frsize
            used_bytes = (stat.f_blocks - stat.f_bfree) * stat.f_frsize

            if total_bytes < 1 * 1024 ** 3:
                continue

            result.append({
                "path": mount_point,
                "used_gb": round(used_bytes / 1024 ** 3, 1),
                "total_gb": round(total_bytes / 1024 ** 3, 1),
                "percent": round(used_bytes / total_bytes * 100, 1)
            })
        except Exception:
            continue

    return sorted(result, key=lambda x: x["used_gb"], reverse=True)


def get_uptime_seconds() -> float:
    try:
        with open(f"{PROC_PATH}/uptime", "r") as f:
            return float(f.read().split()[0])
    except Exception:
        try:
            return time.time() - psutil.boot_time()
        except Exception:
            return 0.0
