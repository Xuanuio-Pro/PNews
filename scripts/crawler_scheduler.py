import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.logging_config import setup_logging
from config.settings import DATA_DIR


setup_logging("crawler_scheduler.log")
LOGGER = logging.getLogger("pnews.scheduler")

LOCK_DIR = DATA_DIR / "crawler_pipeline.lock"
STALE_LOCK_SECONDS = int(os.getenv("PNEWS_CRAWLER_LOCK_STALE_SECONDS", "1800"))
SCHEDULE_TIME = os.getenv("PNEWS_CRAWLER_SCHEDULE_TIME", "07:00")
RETRY_SECONDS = int(os.getenv("PNEWS_CRAWLER_RETRY_SECONDS", "300"))
MAX_RETRIES = int(os.getenv("PNEWS_CRAWLER_MAX_RETRIES", "288"))
RUN_ON_START = os.getenv("PNEWS_CRAWLER_RUN_ON_START", "false").lower() in {
    "1",
    "true",
    "yes",
}


def parse_schedule_time(value):
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except (TypeError, ValueError):
        pass

    LOGGER.warning("Invalid PNEWS_CRAWLER_SCHEDULE_TIME=%r. Using 07:00.", value)
    return 7, 0


def next_run_at(now=None):
    now = now or datetime.now()
    hour, minute = parse_schedule_time(SCHEDULE_TIME)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def acquire_lock():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if LOCK_DIR.exists():
        age = time.time() - LOCK_DIR.stat().st_mtime
        if age > STALE_LOCK_SECONDS:
            LOGGER.warning("Removing stale crawler lock at %s.", LOCK_DIR)
            shutil.rmtree(LOCK_DIR, ignore_errors=True)

    try:
        LOCK_DIR.mkdir()
        LOCK_DIR.chmod(0o777)
    except FileExistsError:
        age = time.time() - LOCK_DIR.stat().st_mtime
        LOGGER.warning(
            "Crawler pipeline lock exists at %s age_seconds=%s. Waiting for retry.",
            LOCK_DIR,
            int(age),
        )
        return False

    marker = LOCK_DIR / "owner.txt"
    marker.write_text(
        f"pid={os.getpid()}\nstarted_at={datetime.now().isoformat(timespec='seconds')}\n",
        encoding="utf-8",
    )
    marker.chmod(0o666)
    return True


def release_lock():
    shutil.rmtree(LOCK_DIR, ignore_errors=True)


def run_command(label, args):
    LOGGER.info("Starting %s...", label)
    subprocess.run(args, cwd=ROOT_DIR, check=True)
    LOGGER.info("%s finished.", label)


def run_pipeline():
    locked = acquire_lock()
    if not locked:
        return False

    python = sys.executable
    card_limit = os.getenv("CARD_LIMIT", "20")

    try:
        run_command("main.py", [python, "-X", "utf8", "main.py"])
        run_command(
            "enrich_articles.py",
            [python, "-X", "utf8", "enrich_articles.py", "--input", "data/exports/new_articles.csv"],
        )
        run_command(
            "generate_news_cards.py",
            [
                python,
                "-X",
                "utf8",
                "generate_news_cards.py",
                "--input",
                "data/exports/new_articles.csv",
                "--limit",
                card_limit,
                "--clean",
            ],
        )
        run_command(
            "sync_cms_from_csv.py",
            [python, "-X", "utf8", "scripts/sync_cms_from_csv.py"],
        )
        LOGGER.info("Crawler pipeline completed successfully.")
        return True
    except subprocess.CalledProcessError as exc:
        LOGGER.error("Crawler pipeline failed at command %s.", exc.cmd, exc_info=True)
        return False
    except Exception:
        LOGGER.error("Crawler pipeline failed unexpectedly.", exc_info=True)
        return False
    finally:
        release_lock()


def run_pipeline_with_retries():
    for attempt in range(MAX_RETRIES + 1):
        if run_pipeline():
            return True
        if attempt >= MAX_RETRIES:
            break
        LOGGER.info(
            "Retrying crawler pipeline in %s seconds. attempt=%s max_retries=%s",
            RETRY_SECONDS,
            attempt + 1,
            MAX_RETRIES,
        )
        time.sleep(RETRY_SECONDS)
    return False


def sleep_until(target):
    while True:
        seconds = (target - datetime.now()).total_seconds()
        if seconds <= 0:
            return
        time.sleep(min(seconds, 300))


def main():
    LOGGER.info(
        "Crawler scheduler started. schedule_time=%s run_on_start=%s",
        SCHEDULE_TIME,
        RUN_ON_START,
    )

    if RUN_ON_START:
        run_pipeline_with_retries()

    while True:
        target = next_run_at()
        LOGGER.info("Next crawler run at %s.", target.strftime("%Y-%m-%d %H:%M:%S"))
        sleep_until(target)
        run_pipeline_with_retries()


if __name__ == "__main__":
    main()
