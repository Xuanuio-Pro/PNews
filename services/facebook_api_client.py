import json
import logging
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

from services.config import get_config_value, get_int_config_value, load_env_file


LOGGER = logging.getLogger(__name__)
TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}
TRANSIENT_GRAPH_CODES = {1, 2, 4, 17, 32, 341, 613}
AUTH_GRAPH_CODES = {10, 190, 200, 463, 467}


@dataclass
class FacebookApiErrorDetails:
    message: str
    code: Optional[int] = None
    subcode: Optional[int] = None
    error_type: str = ""
    http_status: Optional[int] = None
    transient: bool = False
    authentication_error: bool = False
    payload: Optional[dict] = None


class FacebookApiClientError(Exception):
    def __init__(self, details: FacebookApiErrorDetails):
        super().__init__(details.message)
        self.details = details


class FacebookPublishUncertainError(FacebookApiClientError):
    """The feed request timed out, so the server outcome cannot be determined safely."""


class FacebookApiClient:
    def __init__(
        self,
        page_id,
        page_access_token,
        graph_api_version="v25.0",
        timeout_ms=30000,
        max_retries=3,
        base_url="https://graph.facebook.com",
        session=None,
        dry_run=False,
    ):
        self.page_id = str(page_id or "").strip()
        self.page_access_token = str(page_access_token or "").strip()
        version = str(graph_api_version or "v25.0").strip()
        self.graph_api_version = version if version.startswith("v") else f"v{version}"
        self.timeout_seconds = max(1, int(timeout_ms)) / 1000
        self.max_retries = max(0, int(max_retries))
        self.base_url = str(base_url or "https://graph.facebook.com").rstrip("/")
        self.session = session or requests.Session()
        self.dry_run = bool(dry_run)
        if not self.page_id:
            raise ValueError("Thiếu FACEBOOK_PAGE_ID.")
        if not self.page_access_token and not self.dry_run:
            raise ValueError("Thiếu FACEBOOK_PAGE_ACCESS_TOKEN.")

    @classmethod
    def from_env(cls, **overrides):
        load_env_file()
        values = {
            "page_id": get_config_value("FACEBOOK_PAGE_ID", ""),
            "page_access_token": get_config_value("FACEBOOK_PAGE_ACCESS_TOKEN", ""),
            "graph_api_version": get_config_value("FACEBOOK_GRAPH_API_VERSION", "v25.0"),
            "timeout_ms": get_int_config_value("FACEBOOK_API_TIMEOUT_MS", 30000),
            "max_retries": get_int_config_value("FACEBOOK_MAX_RETRIES", 3),
            "base_url": get_config_value("FACEBOOK_GRAPH_API_BASE_URL", "https://graph.facebook.com"),
            "dry_run": _env_bool("FACEBOOK_DRY_RUN", False),
        }
        values.update(overrides)
        return cls(**values)

    def uploadUnpublishedFacebookPhoto(self, media_item, publication_id=""):
        if media_item.facebook_photo_id:
            return {"id": media_item.facebook_photo_id, "reused": True}
        if self.dry_run:
            return {"id": f"dry-photo-{media_item.order}", "dry_run": True}

        data = {
            "published": "false",
            "message": media_item.photo_caption,
            "access_token": self.page_access_token,
        }
        image_url = str(media_item.image_url or "").strip()
        local_path = str(media_item.local_image_path or "").strip()
        if image_url:
            data["url"] = image_url
            return self._request(
                "POST",
                f"{self.page_id}/photos",
                data=data,
                operation="photo_upload",
                publication_id=publication_id,
                article_id=media_item.article_id,
            )
        if not local_path:
            raise ValueError("Media item thiếu imageUrl hoặc localImagePath.")

        path = Path(local_path)
        if not path.exists() or not path.is_file():
            raise ValueError(f"Không tìm thấy ảnh Facebook: {path}")
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        return self._upload_local_file_with_retry(
            path,
            mime_type,
            data,
            publication_id=publication_id,
            article_id=media_item.article_id,
        )

    def createFacebookMultiPhotoPost(self, message, media_fbids, publication_id=""):
        clean_message = str(message or "").strip()
        clean_ids = [str(media_id or "").strip() for media_id in media_fbids if str(media_id or "").strip()]
        if not clean_message:
            raise ValueError("mainCaption không được rỗng.")
        if not clean_ids:
            raise ValueError("Không có Facebook photo ID để tạo bài.")
        if self.dry_run:
            return {"id": f"dry-post-{publication_id or 'preview'}", "dry_run": True}
        data = {"message": clean_message, "access_token": self.page_access_token}
        for index, media_id in enumerate(clean_ids):
            data[f"attached_media[{index}]"] = json.dumps(
                {"media_fbid": media_id}, ensure_ascii=False
            )
        return self._request(
            "POST",
            f"{self.page_id}/feed",
            data=data,
            operation="feed_publish",
            publication_id=publication_id,
            retry_timeouts=False,
        )

    def _upload_local_file_with_retry(self, path, mime_type, data, publication_id, article_id):
        attempts = self.max_retries + 1
        last_error = None
        for attempt in range(attempts):
            try:
                with path.open("rb") as handle:
                    response = self.session.post(
                        self._url(f"{self.page_id}/photos"),
                        data=data,
                        files={"source": (path.name, handle, mime_type)},
                        timeout=self.timeout_seconds,
                    )
                return self._parse_response(response)
            except requests.RequestException as exc:
                last_error = self._network_error(exc)
            except FacebookApiClientError as exc:
                last_error = exc
            if not self._should_retry(last_error, attempt, attempts):
                raise last_error
            self._log_retry("photo_upload", publication_id, article_id, attempt + 1, last_error)
            time.sleep(self._backoff_seconds(attempt))
        raise last_error

    def _request(
        self,
        method,
        target,
        data=None,
        operation="request",
        publication_id="",
        article_id="",
        retry_timeouts=True,
    ):
        attempts = self.max_retries + 1
        last_error = None
        for attempt in range(attempts):
            try:
                response = self.session.request(
                    method,
                    self._url(target),
                    data=data,
                    timeout=self.timeout_seconds,
                )
                return self._parse_response(response)
            except requests.Timeout as exc:
                details = self._network_error(exc).details
                if not retry_timeouts:
                    raise FacebookPublishUncertainError(details) from exc
                last_error = FacebookApiClientError(details)
            except requests.RequestException as exc:
                network_error = self._network_error(exc)
                if not retry_timeouts:
                    raise FacebookPublishUncertainError(network_error.details) from exc
                last_error = network_error
            except FacebookApiClientError as exc:
                last_error = exc
            if not self._should_retry(last_error, attempt, attempts):
                raise last_error
            self._log_retry(operation, publication_id, article_id, attempt + 1, last_error)
            time.sleep(self._backoff_seconds(attempt))
        raise last_error

    def _parse_response(self, response):
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text[:1000]}
        if response.ok and not (isinstance(payload, dict) and payload.get("error")):
            return payload
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = _optional_int(error.get("code"))
        status = response.status_code
        transient = status in TRANSIENT_HTTP_STATUSES or code in TRANSIENT_GRAPH_CODES
        authentication_error = code in AUTH_GRAPH_CODES
        details = FacebookApiErrorDetails(
            message=str(error.get("message") or f"Facebook API HTTP {status}"),
            code=code,
            subcode=_optional_int(error.get("error_subcode")),
            error_type=str(error.get("type") or ""),
            http_status=status,
            transient=bool(transient and not authentication_error),
            authentication_error=authentication_error,
            payload=payload,
        )
        raise FacebookApiClientError(details)

    def _network_error(self, exc):
        return FacebookApiClientError(
            FacebookApiErrorDetails(
                message=f"Facebook network error: {type(exc).__name__}",
                transient=True,
            )
        )

    @staticmethod
    def _should_retry(error, attempt, attempts):
        return bool(
            error
            and attempt + 1 < attempts
            and error.details.transient
            and not error.details.authentication_error
        )

    @staticmethod
    def _backoff_seconds(attempt):
        return min(2 ** attempt, 8)

    @staticmethod
    def _log_retry(operation, publication_id, article_id, attempt, error):
        LOGGER.warning(
            "publicationId=%s articleId=%s event=facebook_retry operation=%s attempt=%s code=%s",
            publication_id,
            article_id,
            operation,
            attempt,
            error.details.code,
        )

    def _url(self, target):
        return f"{self.base_url}/{self.graph_api_version}/{str(target).lstrip('/')}"


def _optional_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        value = get_config_value(name, "true" if default else "false")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


uploadUnpublishedFacebookPhoto = FacebookApiClient.uploadUnpublishedFacebookPhoto
createFacebookMultiPhotoPost = FacebookApiClient.createFacebookMultiPhotoPost
