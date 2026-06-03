import html
import json
import os
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


class TelegramNotifier:
    def __init__(self, bot_token=None, default_chat_id=None, timeout=30):
        config = self._load_config()
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN") or config.get("TELEGRAM_BOT_TOKEN") or ""
        self.default_chat_id = (
            default_chat_id
            or os.getenv("TELEGRAM_DEFAULT_CHAT_ID")
            or config.get("TELEGRAM_DEFAULT_CHAT_ID")
            or ""
        )
        self.enable_notify = self._parse_bool(
            os.getenv("ENABLE_TELEGRAM_NOTIFY", config.get("ENABLE_TELEGRAM_NOTIFY", True))
        )
        self.timeout = timeout

    def _load_config(self):
        if not CONFIG_PATH.exists():
            return {}
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as file:
                return json.load(file)
        except (OSError, json.JSONDecodeError):
            return {}

    def _api_url(self, method):
        if not self.bot_token:
            raise ValueError("Telegram bot token is not configured.")
        return f"https://api.telegram.org/bot{self.bot_token}/{method}"

    def _parse_bool(self, value):
        if isinstance(value, bool):
            return value
        if value is None:
            return True
        return str(value).strip().lower() not in {"0", "false", "no", "off", ""}

    def _chat_id(self, chat_id=None):
        target = str(chat_id or self.default_chat_id or "").strip()
        if not target:
            raise ValueError("Telegram default chat id is not configured.")
        return target

    def _raise_for_telegram_error(self, response):
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.ok and payload.get("ok", True):
            return
        description = str(payload.get("description") or response.reason or "Telegram API error")
        raise RuntimeError(f"Telegram API error: {description[:300]}")

    def _sanitize_error(self, exc):
        message = str(exc)
        if self.bot_token:
            message = message.replace(self.bot_token, "***")
        return message[:300]

    def _trim(self, value, limit):
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)].rstrip() + "..."

    def build_article_message(self, article, max_summary_chars=450):
        category = article.get("category") or article.get("content_topic") or "Tin tức"
        topic = article.get("content_topic") or category
        title = article.get("title") or "Không có tiêu đề"
        summary = article.get("summary") or "Chưa có tóm tắt."
        source = article.get("source") or "PNews"
        url = article.get("url") or ""
        published_at = article.get("published_at") or article.get("crawled_at") or ""

        safe_category = html.escape(self._trim(category, 120))
        safe_topic = html.escape(self._trim(topic, 120))
        safe_title = html.escape(self._trim(title, 300))
        safe_summary = html.escape(self._trim(summary, max_summary_chars))
        safe_source = html.escape(self._trim(source, 160))
        safe_url = html.escape(self._trim(url, 900), quote=True)
        safe_published_at = html.escape(self._trim(published_at, 80))
        published_line = f"🗓 Ngày đăng: {safe_published_at}\n" if safe_published_at else ""

        return (
            f"📰 PNews | {safe_category}\n\n"
            f"<b>{safe_title}</b>\n\n"
            f"📝 Tóm tắt:\n"
            f"{safe_summary}\n\n"
            f"📌 Nguồn: {safe_source}\n"
            f"{published_line}"
            f"🏷 Chủ đề: {safe_topic}\n"
            f"🔗 Đọc bài viết: {safe_url}"
        )

    def _fit_article_message(self, article, max_length):
        for summary_limit in (450, 320, 220, 140, 80, 0):
            text = self.build_article_message(article, max_summary_chars=summary_limit)
            if len(text) <= max_length:
                return text
        compact = dict(article)
        compact["summary"] = ""
        compact["title"] = self._trim(article.get("title"), 120)
        compact["url"] = self._trim(article.get("url"), 500)
        text = self.build_article_message(compact, max_summary_chars=0)
        return text if len(text) <= max_length else text[: max_length - 3].rstrip() + "..."

    def send_message(self, text, chat_id=None, disable_web_page_preview=False):
        payload = {
            "chat_id": self._chat_id(chat_id),
            "text": str(text or "")[:4096],
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_web_page_preview,
        }
        try:
            response = requests.post(self._api_url("sendMessage"), json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise RuntimeError(f"Telegram request failed: {self._sanitize_error(exc)}") from exc
        self._raise_for_telegram_error(response)
        return response.json()

    def send_photo(self, image_path, caption, chat_id=None):
        path = Path(image_path)
        if not path.exists() or not path.is_file():
            return self.send_message(caption, chat_id=chat_id)

        data = {
            "chat_id": self._chat_id(chat_id),
            "caption": str(caption or "")[:1024],
            "parse_mode": "HTML",
        }
        with path.open("rb") as photo:
            try:
                response = requests.post(
                    self._api_url("sendPhoto"),
                    data=data,
                    files={"photo": photo},
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise RuntimeError(f"Telegram request failed: {self._sanitize_error(exc)}") from exc
        self._raise_for_telegram_error(response)
        return response.json()

    def send_article(self, article, image_path=None, chat_id=None):
        if image_path:
            caption = self._fit_article_message(article, 1024)
            return self.send_photo(image_path, caption, chat_id=chat_id)
        text = self._fit_article_message(article, 4096)
        return self.send_message(text, chat_id=chat_id, disable_web_page_preview=False)
