import asyncio
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass

from telethon.errors import RPCError

from config import (
    ADMIN_IDS,
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


@dataclass(frozen=True)
class ServerHealth:
    cpu_percent: float
    load_average: float
    cpu_count: int
    load_percent: float
    memory_percent: float
    disk_percent: float
    event_loop_lag: float = 0.0


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
    global _previous_cpu_times
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
    if total_delta <= 0:
        return 0.0
    return max(0.0, min(100.0, (total_delta - idle_delta) / total_delta * 100))


def collect_server_health(event_loop_lag: float = 0.0) -> ServerHealth:
    cpu_count = max(os.cpu_count() or 1, 1)
    try:
        one_minute_load = os.getloadavg()[0]
    except OSError:
        one_minute_load = 0.0
    disk = shutil.disk_usage(".")
    return ServerHealth(
        cpu_percent=_cpu_percent(),
        load_average=one_minute_load,
        cpu_count=cpu_count,
        load_percent=one_minute_load / cpu_count * 100,
        memory_percent=_memory_percent(),
        disk_percent=disk.used / disk.total * 100 if disk.total else 0.0,
        event_loop_lag=max(event_loop_lag, 0.0),
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
                    "Server tarifini oshirish yoki yuklamani tekshirish tavsiya qilinadi.",
                )

            if recovered:
                active_issues.difference_update(recovered)
                await _notify_admins(
                    bot_client,
                    "✅ <b>Server holati normallashdi.</b>\n\n" + format_health(health),
                )
        except Exception:
            logger.exception("Server holatini tekshirishda xatolik")
