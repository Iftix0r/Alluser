import asyncio
import html
import logging
import math
import os
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from telethon.errors import RPCError

from config import (
    ADMIN_IDS,
    CURRENT_VPS_PLAN,
    HEALTH_CHECK_INTERVAL_SECONDS,
    HEALTH_CONSECUTIVE_CHECKS,
    HEALTH_CPU_THRESHOLD_PERCENT,
    HEALTH_DISK_THRESHOLD_PERCENT,
    HEALTH_EVENT_LOOP_LAG_SECONDS,
    HEALTH_LOAD_THRESHOLD_PERCENT,
    HEALTH_MEMORY_THRESHOLD_PERCENT,
)

logger = logging.getLogger(__name__)
_latest_health = None
_cpu_lock = threading.Lock()
_previous_cpu_times = None
_previous_process_times = {}
_last_cpu_total_delta = 0

VPS_PLANS = (
    ("VPS 1", 1, 1, 60_000),
    ("VPS 2", 2, 2, 110_000),
    ("VPS 3", 2, 4, 200_000),
    ("VPS 4", 4, 8, 380_000),
    ("VPS 5", 6, 16, 760_000),
    ("VPS 6", 8, 32, 1_520_000),
    ("VPS 7", 12, 48, 2_280_000),
    ("VPS 8", 16, 64, 3_040_000),
)


@dataclass(frozen=True)
class ProcessUsage:
    pid: int
    name: str
    cpu_percent: float
    memory_mb: float


@dataclass(frozen=True)
class ServerHealth:
    cpu_percent: float
    load_average: float
    cpu_count: int
    load_percent: float
    memory_percent: float
    disk_percent: float
    event_loop_lag: float = 0.0
    top_processes: tuple[ProcessUsage, ...] = ()


def _memory_percent() -> float:
    """Linux /proc orqali real ishlatilayotgan RAM foizini qaytaradi."""
    values = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as meminfo:
            for line in meminfo:
                key, raw = line.split(":", 1)
                values[key] = int(raw.strip().split()[0])
    except (OSError, ValueError):
        return 0.0
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    return ((total - available) / total * 100) if total else 0.0


def _cpu_percent() -> float:
    """Ikki o'lchov oralig'idagi real CPU bandligini /proc/stat orqali hisoblaydi."""
    global _last_cpu_total_delta, _previous_cpu_times
    try:
        with open("/proc/stat", encoding="utf-8") as proc_stat:
            values = [int(value) for value in proc_stat.readline().split()[1:]]
    except (OSError, ValueError):
        return 0.0
    if len(values) < 5:
        return 0.0
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    with _cpu_lock:
        previous = _previous_cpu_times
        _previous_cpu_times = (total, idle)
    if previous is None:
        # Birinchi admin tekshiruvida ham 0% ko'rsatib qolmasligi uchun juda qisqa
        # namunadan real bandlikni hisoblaymiz (bu funksiya worker thread'da ishlaydi).
        time.sleep(0.1)
        return _cpu_percent()
    total_delta = total - previous[0]
    idle_delta = idle - previous[1]
    _last_cpu_total_delta = max(total_delta, 0)
    if total_delta <= 0:
        return 0.0
    return max(0.0, min(100.0, (total_delta - idle_delta) / total_delta * 100))


def _top_processes(limit: int = 5) -> tuple[ProcessUsage, ...]:
    """Oxirgi ikki health-check oralig'ida eng ko'p CPU ishlatgan jarayonlar."""
    global _previous_process_times
    current_times = {}
    process_data = []
    page_size = os.sysconf("SC_PAGE_SIZE")
    for stat_path in Path("/proc").glob("[0-9]*/stat"):
        try:
            pid = int(stat_path.parent.name)
            raw = stat_path.read_text(encoding="utf-8")
            close_paren = raw.rfind(")")
            name = raw[raw.find("(") + 1 : close_paren]
            fields = raw[close_paren + 2 :].split()
            process_ticks = int(fields[11]) + int(fields[12])
            current_times[pid] = process_ticks
            previous_ticks = _previous_process_times.get(pid)
            if previous_ticks is None or _last_cpu_total_delta <= 0:
                continue
            cpu_percent = max(0.0, (process_ticks - previous_ticks) / _last_cpu_total_delta * 100)
            rss_pages = int((stat_path.parent / "statm").read_text().split()[1])
            memory_mb = rss_pages * page_size / 1024 / 1024
            process_data.append(ProcessUsage(pid, name, cpu_percent, memory_mb))
        except (OSError, ValueError, IndexError):
            continue
    _previous_process_times = current_times
    process_data.sort(key=lambda item: (item.cpu_percent, item.memory_mb), reverse=True)
    return tuple(process_data[:limit])


def collect_server_health(event_loop_lag: float = 0.0) -> ServerHealth:
    cpu_count = max(os.cpu_count() or 1, 1)
    try:
        one_minute_load = os.getloadavg()[0]
    except OSError:
        one_minute_load = 0.0
    disk = shutil.disk_usage(".")
    cpu_percent = _cpu_percent()
    return ServerHealth(
        cpu_percent=cpu_percent,
        load_average=one_minute_load,
        cpu_count=cpu_count,
        load_percent=one_minute_load / cpu_count * 100,
        memory_percent=_memory_percent(),
        disk_percent=disk.used / disk.total * 100 if disk.total else 0.0,
        event_loop_lag=max(event_loop_lag, 0.0),
        top_processes=_top_processes(),
    )


def get_server_health_snapshot() -> ServerHealth:
    return _latest_health or collect_server_health()


def health_issues(health: ServerHealth) -> dict[str, str]:
    issues = {}
    if health.cpu_percent >= HEALTH_CPU_THRESHOLD_PERCENT:
        issues["cpu"] = f"CPU bandligi: {health.cpu_percent:.1f}%"
    if health.load_percent >= HEALTH_LOAD_THRESHOLD_PERCENT:
        issues["load"] = (
            f"System load: {health.load_average:.2f} / {health.cpu_count} yadro "
            f"({health.load_percent:.1f}%)"
        )
    if health.memory_percent >= HEALTH_MEMORY_THRESHOLD_PERCENT:
        issues["memory"] = f"RAM: {health.memory_percent:.1f}%"
    if health.disk_percent >= HEALTH_DISK_THRESHOLD_PERCENT:
        issues["disk"] = f"Disk: {health.disk_percent:.1f}%"
    if health.event_loop_lag >= HEALTH_EVENT_LOOP_LAG_SECONDS:
        issues["event_loop"] = f"Bot kechikishi: {health.event_loop_lag:.1f} soniya"
    return issues


def format_health(health: ServerHealth) -> str:
    status = "⚠️ Muammo aniqlandi" if health_issues(health) else "✅ Holat yaxshi"
    advice = ""
    if health.load_percent >= HEALTH_LOAD_THRESHOLD_PERCENT:
        if health.cpu_percent >= HEALTH_CPU_THRESHOLD_PERCENT:
            advice = "\n\n💡 CPU quvvati yetishmayapti; tarif/yadro sonini oshirish foyda beradi."
        else:
            advice = (
                "\n\n💡 Load yuqori, lekin CPU to'liq band emas; disk I/O, baza yoki "
                "bloklangan jarayonlarni tekshirish kerak."
            )
    elif health.memory_percent >= HEALTH_MEMORY_THRESHOLD_PERCENT:
        advice = "\n\n💡 RAM yetishmayapti; xotira hajmini oshirish tavsiya qilinadi."
    elif health.disk_percent >= HEALTH_DISK_THRESHOLD_PERCENT:
        advice = "\n\n💡 Diskni tozalash yoki hajmini oshirish kerak."
    current_plan = next((plan for plan in VPS_PLANS if plan[0] == CURRENT_VPS_PLAN), None)
    plan_text = ""
    if current_plan:
        plan_text = (
            f"\n\n📦 Joriy tarif: {current_plan[0]} — {current_plan[1]} yadro, "
            f"{current_plan[2]} GB RAM, {current_plan[3]:,} so'm".replace(",", " ")
        )
    if health.cpu_percent >= HEALTH_CPU_THRESHOLD_PERCENT and health.load_percent >= HEALTH_LOAD_THRESHOLD_PERCENT:
        target_cores = max(health.cpu_count + 1, math.ceil(health.load_average / 0.7))
        recommended = next(
            (plan for plan in VPS_PLANS if plan[1] >= target_cores),
            VPS_PLANS[-1],
        )
        plan_text += (
            f"\n🚀 Tavsiya: {recommended[0]} — {recommended[1]} yadro, "
            f"{recommended[2]} GB RAM, {recommended[3]:,} so'm/oy".replace(",", " ")
        )

    processes_text = ""
    if health.top_processes:
        process_lines = ["\n\n🔎 <b>Eng ko'p resurs ishlatayotgan jarayonlar:</b>"]
        for process in health.top_processes:
            process_lines.append(
                f"• {html.escape(process.name)} (PID {process.pid}) — CPU {process.cpu_percent:.1f}%, "
                f"RAM {process.memory_mb:.0f} MB"
            )
        processes_text = "\n".join(process_lines)
    else:
        processes_text = "\n\n🔎 Jarayonlar tahlili uchun keyingi monitor o'lchovi kutilmoqda."

    return (
        f"🖥 <b>Server holati</b>\n\n"
        f"{status}\n"
        f"⚙️ CPU bandligi: {health.cpu_percent:.1f}%\n"
        f"📈 System load (1 daqiqa): {health.load_average:.2f} / "
        f"{health.cpu_count} yadro ({health.load_percent:.1f}%)\n"
        f"🧠 RAM: {health.memory_percent:.1f}%\n"
        f"💾 Disk: {health.disk_percent:.1f}%\n"
        f"⏱ Bot kechikishi: {health.event_loop_lag:.1f} soniya"
        f"{advice}"
        f"{plan_text}"
        f"{processes_text}"
    )


async def _notify_admins(bot_client, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot_client.send_message(admin_id, text, parse_mode="html")
        except (RPCError, ValueError):
            logger.warning("Server holati adminga yuborilmadi: admin=%s", admin_id)


async def health_monitor_loop(bot_client) -> None:
    """Ketma-ket yomon o'lchovdan keyin ogohlantiradi va tiklanishni ham xabar qiladi."""
    global _latest_health
    loop = asyncio.get_running_loop()
    expected = loop.time() + HEALTH_CHECK_INTERVAL_SECONDS
    issue_counts: dict[str, int] = {}
    active_issues: set[str] = set()

    while True:
        await asyncio.sleep(HEALTH_CHECK_INTERVAL_SECONDS)
        now = loop.time()
        lag = max(0.0, now - expected)
        expected = now + HEALTH_CHECK_INTERVAL_SECONDS

        try:
            health = await asyncio.to_thread(collect_server_health, lag)
            _latest_health = health
            issues = health_issues(health)
            for key in set(issue_counts) | set(issues):
                issue_counts[key] = issue_counts.get(key, 0) + 1 if key in issues else 0

            newly_active = {
                key
                for key, count in issue_counts.items()
                if (
                    (key == "event_loop" or count >= HEALTH_CONSECUTIVE_CHECKS)
                    and key not in active_issues
                )
            }
            recovered = {key for key in active_issues if key not in issues}

            if newly_active:
                active_issues.update(newly_active)
                details = "\n".join(f"• {issues[key]}" for key in newly_active)
                await _notify_admins(
                    bot_client,
                    "🚨 <b>Server kuchi yetishmayapti!</b>\n\n"
                    f"{details}\n\n"
                    + format_health(health),
                )

            if recovered:
                active_issues.difference_update(recovered)
                await _notify_admins(
                    bot_client,
                    "✅ <b>Server holati normallashdi.</b>\n\n" + format_health(health),
                )
        except Exception:
            logger.exception("Server holatini tekshirishda xatolik")
