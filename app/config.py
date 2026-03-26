import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
SERVER_NAME = os.getenv("SERVER_NAME", "server")

RAM_PROCESS_WARN = float(os.getenv("RAM_PROCESS_WARN", "5"))
RAM_PROCESS_CRIT = float(os.getenv("RAM_PROCESS_CRIT", "15"))

RAM_TOTAL_WARN = float(os.getenv("RAM_TOTAL_WARN", "75"))
RAM_TOTAL_CRIT = float(os.getenv("RAM_TOTAL_CRIT", "90"))

CPU_PROCESS_WARN = float(os.getenv("CPU_PROCESS_WARN", "50"))
CPU_PROCESS_CRIT = float(os.getenv("CPU_PROCESS_CRIT", "80"))

REPEAT_ALERT_MIN = int(os.getenv("REPEAT_ALERT_MIN", "30"))
CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", "2"))

STATE_FILE = os.getenv("STATE_FILE", "/app/data/monitor_state.json")

PROC_PATH = os.getenv("PROC_PATH", "/proc")
