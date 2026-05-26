import json
import logging
import sqlite3
import unicodedata
from pathlib import Path

from services.notifiers.telegram_notifier import TelegramNotifier


BASE_DIR = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, db_path="data/cms.sqlite3"):
        self.db_path = self._resolve_path(db_path)

    def _resolve_path(self, path):
        candidate = Path(path or "")
        if not candidate.is_absolute():
            candidate = BASE_DIR / candidate
        return candidate

    def connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_tables(self):
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message_preview TEXT,
                    error_message TEXT,
                    response_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_unique
                ON notification_logs(article_id, platform, target_id)
                """
            )
            conn.commit()

    def was_sent(self, article_id, platform, target_id):
        self.ensure_tables()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM notification_logs
                WHERE article_id = ? AND platform = ? AND target_id = ? AND status = 'sent'
                LIMIT 1
                """,
                (int(article_id), platform, str(target_id)),
            ).fetchone()
            return row is not None

    def log_result(
        self,
        article_id,
        platform,
        target_id,
        status,
        message_preview="",
        error_message=None,
        response=None,
    ):
        self.ensure_tables()
        response_json = ""
        if response is not None:
            try:
                response_json = json.dumps(response, ensure_ascii=False)
            except TypeError:
                response_json = json.dumps(str(response), ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notification_logs (
                    article_id, platform, target_id, status,
                    message_preview, error_message, response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(article_id, platform, target_id) DO UPDATE SET
                    status = excluded.status,
                    message_preview = excluded.message_preview,
                    error_message = excluded.error_message,
                    response_json = excluded.response_json,
                    created_at = CURRENT_TIMESTAMP
                """,
                (
                    int(article_id),
                    platform,
                    str(target_id),
                    status,
                    str(message_preview or "")[:500],
                    str(error_message or "")[:500] if error_message else None,
                    response_json,
                ),
            )
            conn.commit()

    def get_article_by_id(self, article_id):
        if not str(article_id).isdigit():
            return None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM articles WHERE id = ?", (int(article_id),)).fetchone()
            return dict(row) if row else None

    def is_publishable(self, article):
        status = str((article or {}).get("status") or "").strip()
        normalized = unicodedata.normalize("NFKD", status).encode("ascii", "ignore").decode("ascii").lower()
        normalized = " ".join(normalized.split())
        return status in {"Đã đăng"} or normalized in {"approved", "published", "da dang"}

    def find_article_image(self, article):
        if not article:
            return None

        for key in ("news_card_path", "image_path", "uploaded_image", "local_image"):
            path = self._existing_local_path(article.get(key))
            if path:
                return path

        article_id = article.get("id")
        image_root = BASE_DIR / "data" / "generated_images"
        if not article_id or not image_root.exists():
            return None

        patterns = [
            f"**/article_{article_id}.jpg",
            f"**/article_{article_id}.png",
            f"**/{article_id}.jpg",
            f"**/{article_id}.png",
        ]
        for pattern in patterns:
            for path in image_root.glob(pattern):
                if path.is_file():
                    return path
        return None

    def _existing_local_path(self, value):
        if not value:
            return None
        text = str(value).strip()
        if text.startswith(("http://", "https://")):
            return None
        path = Path(text)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path if path.exists() and path.is_file() else None

    def _telegram_target_id(self, notifier, target_id=None):
        target = str(target_id or notifier.default_chat_id or "").strip()
        if not target:
            raise ValueError("Telegram default chat id is not configured.")
        return target

    def send_article_to_telegram(self, article, target_id=None):
        notifier = TelegramNotifier(default_chat_id=target_id)
        target = self._telegram_target_id(notifier, target_id)
        image_path = self.find_article_image(article)
        response = notifier.send_article(article, image_path=image_path, chat_id=target)
        preview = notifier.build_article_message(article)[:500]
        self.log_result(article["id"], "telegram", target, "sent", message_preview=preview, response=response)
        return response

    def send_selected_articles_to_telegram(self, article_ids, target_id=None):
        self.ensure_tables()
        result = {"sent": 0, "skipped": 0, "failed": 0, "messages": []}
        notifier = TelegramNotifier(default_chat_id=target_id)
        target = self._telegram_target_id(notifier, target_id)

        clean_ids = []
        for raw_id in article_ids or []:
            if str(raw_id).isdigit():
                clean_ids.append(int(raw_id))

        for article_id in clean_ids:
            article = self.get_article_by_id(article_id)
            if not article:
                result["skipped"] += 1
                result["messages"].append(f"Bỏ qua bài #{article_id}: không tồn tại.")
                continue

            if not self.is_publishable(article):
                result["skipped"] += 1
                self.log_result(
                    article_id,
                    "telegram",
                    target,
                    "skipped",
                    message_preview=str(article.get("title") or "")[:500],
                    error_message="Article is not approved/published.",
                )
                result["messages"].append(f"Bỏ qua bài #{article_id}: chưa được đăng.")
                continue

            if self.was_sent(article_id, "telegram", target):
                result["skipped"] += 1
                result["messages"].append(f"Bỏ qua bài #{article_id}: đã gửi Telegram.")
                continue

            try:
                image_path = self.find_article_image(article)
                response = notifier.send_article(article, image_path=image_path, chat_id=target)
                preview = notifier.build_article_message(article)[:500]
                self.log_result(article_id, "telegram", target, "sent", message_preview=preview, response=response)
                result["sent"] += 1
            except Exception as exc:
                safe_error = str(exc)[:500]
                LOGGER.error("Failed to send article %s to Telegram: %s", article_id, safe_error)
                self.log_result(
                    article_id,
                    "telegram",
                    target,
                    "failed",
                    message_preview=str(article.get("title") or "")[:500],
                    error_message=safe_error,
                )
                result["failed"] += 1
                result["messages"].append(f"Lỗi bài #{article_id}: {safe_error}")

        return result

    def send_latest_approved_to_telegram(self, limit=5, target_id=None):
        self.ensure_tables()
        limit = max(1, int(limit or 5))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM articles
                WHERE status IN ('approved', 'published', 'Đã đăng')
                ORDER BY
                    date(COALESCE(NULLIF(crawled_at, ''), created_at)) DESC,
                    datetime(COALESCE(NULLIF(crawled_at, ''), created_at)) DESC,
                    id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return self.send_selected_articles_to_telegram([row["id"] for row in rows], target_id=target_id)
