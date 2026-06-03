import logging
import mimetypes
import os
import json
from pathlib import Path
from typing import Any, Mapping

import requests

from services.config import load_env_file


LOGGER = logging.getLogger(__name__)
DEFAULT_GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE_URL = "https://graph.facebook.com"


class FacebookPublishError(Exception):
    """Base error for Facebook publish failures."""


class FacebookConfigError(FacebookPublishError):
    """Raised when Facebook environment configuration is missing."""


class FacebookAPIError(FacebookPublishError):
    def __init__(self, message, response=None, status_code=None):
        super().__init__(message)
        self.response = response
        self.status_code = status_code


def _article_value(article, key, default=""):
    if isinstance(article, Mapping):
        return article.get(key, default)
    try:
        return article[key]
    except (KeyError, IndexError, TypeError):
        return default


def _clean(value):
    return str(value or "").strip()


def _config():
    load_env_file()
    page_id = _clean(os.environ.get("FACEBOOK_PAGE_ID"))
    token = _clean(os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN"))
    version = _clean(os.environ.get("FACEBOOK_GRAPH_API_VERSION")) or DEFAULT_GRAPH_API_VERSION
    version = version if version.startswith("v") else f"v{version}"

    missing = []
    if not page_id:
        missing.append("FACEBOOK_PAGE_ID")
    if not token:
        missing.append("FACEBOOK_PAGE_ACCESS_TOKEN")
    if missing:
        raise FacebookConfigError("Thiếu biến môi trường: " + ", ".join(missing))

    return {
        "page_id": page_id,
        "access_token": token,
        "version": version,
    }


def mask_token(token):
    token = _clean(token)
    if not token:
        return ""
    if len(token) <= 10:
        return token[:2] + "..." + token[-2:]
    return token[:4] + "..." + token[-3:]


def buildFacebookCaption(article):
    title = _clean(_article_value(article, "title")) or "Cập nhật tin tức mới"
    summary = (
        _clean(_article_value(article, "summary"))
        or "Bản tin được hệ thống PNews tổng hợp tự động từ các nguồn tin đáng tin cậy."
    )
    source = _clean(_article_value(article, "source")) or "PNews"
    url = _clean(_article_value(article, "url"))

    parts = [
        "📌 TIN MỚI TỪ PNEWS",
        "",
        title,
        "",
        summary,
        "",
        f"Nguồn: {source}",
    ]
    if url:
        parts.append(f"🔗 Xem chi tiết: {url}")
    parts.extend(
        [
            "",
            "PNews tự động tổng hợp và chọn lọc các tin tức nổi bật về giáo dục, khoa học, công nghệ và hoạt động PTIT.",
            "",
            "#PNews #PTIT #TinTucCongNghe #GiaoDuc #KhoaHocCongNghe",
        ]
    )
    return "\n".join(parts)


def resolvePosterImage(article):
    for key in ("generated_poster_image", "image_path", "thumbnail"):
        value = _clean(_article_value(article, key))
        if value:
            return value
    return "PNews.png"


def _graph_url(config, target):
    return f"{GRAPH_API_BASE_URL}/{config['version']}/{target.lstrip('/')}"


def _response_json(response):
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def _friendly_facebook_error(payload, status_code=None):
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return f"Facebook API error HTTP {status_code or ''}".strip()

    message = _clean(error.get("message")) or "Facebook API trả về lỗi."
    code = error.get("code")
    error_type = _clean(error.get("type"))
    lowered = message.lower()

    if code in {190, 463, 467} or "expired" in lowered:
        return "Page Access Token hết hạn hoặc không hợp lệ."
    if "pages_manage_posts" in lowered or "permission" in lowered or code in {10, 200, 298}:
        return "Token thiếu quyền pages_manage_posts/pages_read_engagement hoặc Page chưa cấp quyền."
    if code in {4, 17, 32, 613} or "rate" in lowered:
        return "Facebook API đang giới hạn tần suất. Hãy thử lại sau."
    if code == 100 and ("object" in lowered or "page" in lowered):
        return "Sai Page ID hoặc Page không tồn tại/không truy cập được."

    detail = f"Facebook API error"
    if code:
        detail += f" code={code}"
    if error_type:
        detail += f" type={error_type}"
    return f"{detail}: {message}"


def _raise_for_api_error(response):
    payload = _response_json(response)
    if response.ok and not (isinstance(payload, dict) and payload.get("error")):
        return payload
    raise FacebookAPIError(
        _friendly_facebook_error(payload, response.status_code),
        response=payload,
        status_code=response.status_code,
    )


def _post_feed(payload):
    config = _config()
    url = _graph_url(config, f"{config['page_id']}/feed")
    safe_payload = {key: value for key, value in payload.items() if key != "access_token"}
    LOGGER.info(
        "Facebook publish request page_id=%s token=%s payload=%s",
        config["page_id"],
        mask_token(config["access_token"]),
        safe_payload,
    )
    response = requests.post(
        url,
        data={**payload, "access_token": config["access_token"]},
        timeout=30,
    )
    payload_json = _raise_for_api_error(response)
    LOGGER.info("Facebook API response page_id=%s response=%s", config["page_id"], payload_json)
    return payload_json


def _post_photo(message, image_path):
    config = _config()
    path = Path(image_path)
    if not path.exists() or not path.is_file():
        raise FacebookPublishError(f"Khong tim thay anh dang Facebook: {path}")

    url = _graph_url(config, f"{config['page_id']}/photos")
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    LOGGER.info(
        "Facebook photo publish request page_id=%s token=%s image=%s",
        config["page_id"],
        mask_token(config["access_token"]),
        path,
    )
    with path.open("rb") as file_handle:
        response = requests.post(
            url,
            data={
                "message": _clean(message),
                "access_token": config["access_token"],
            },
            files={"source": (path.name, file_handle, mime_type)},
            timeout=60,
        )
    payload_json = _raise_for_api_error(response)
    LOGGER.info("Facebook photo API response page_id=%s response=%s", config["page_id"], payload_json)
    return payload_json


def _upload_unpublished_photo(image_path):
    config = _config()
    path = Path(image_path)
    if not path.exists() or not path.is_file():
        raise FacebookPublishError(f"Khong tim thay anh dang Facebook: {path}")

    url = _graph_url(config, f"{config['page_id']}/photos")
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    LOGGER.info(
        "Facebook unpublished photo upload page_id=%s token=%s image=%s",
        config["page_id"],
        mask_token(config["access_token"]),
        path,
    )
    with path.open("rb") as file_handle:
        response = requests.post(
            url,
            data={
                "published": "false",
                "access_token": config["access_token"],
            },
            files={"source": (path.name, file_handle, mime_type)},
            timeout=60,
        )
    payload_json = _raise_for_api_error(response)
    LOGGER.info("Facebook unpublished photo response page_id=%s response=%s", config["page_id"], payload_json)
    return payload_json


def _post_feed_with_media(message, media_fbids):
    clean_message = _clean(message)
    clean_media_ids = [_clean(media_id) for media_id in (media_fbids or []) if _clean(media_id)]
    if not clean_message:
        raise FacebookPublishError("Noi dung dang Facebook khong duoc de trong.")
    if not clean_media_ids:
        raise FacebookPublishError("Thieu anh dinh kem Facebook.")

    payload = {"message": clean_message}
    for index, media_id in enumerate(clean_media_ids):
        payload[f"attached_media[{index}]"] = json.dumps({"media_fbid": media_id})
    return _post_feed(payload)


def publishLinkPost(article):
    caption = _clean(_article_value(article, "facebook_caption")) or buildFacebookCaption(article)
    link = _clean(_article_value(article, "url"))
    if not link:
        return publishTextPost(caption)
    return _post_feed({"message": caption, "link": link})


def publishPhotoPost(message, image_path):
    clean_message = _clean(message)
    if not clean_message:
        raise FacebookPublishError("Noi dung dang Facebook khong duoc de trong.")
    return _post_photo(clean_message, image_path)


def publishMultiPhotoPost(message, image_paths):
    paths = [Path(path) for path in (image_paths or []) if _clean(path)]
    if not paths:
        raise FacebookPublishError("Thieu anh dinh kem Facebook.")
    if len(paths) == 1:
        return publishPhotoPost(message, paths[0])

    media_ids = []
    for path in paths:
        response = _upload_unpublished_photo(path)
        photo_id = _clean(response.get("id"))
        if not photo_id:
            raise FacebookPublishError("Facebook API khong tra ve photo_id.")
        media_ids.append(photo_id)
    return _post_feed_with_media(message, media_ids)


def publishTextPost(message):
    clean_message = _clean(message)
    if not clean_message:
        raise FacebookPublishError("Nội dung đăng Facebook không được để trống.")
    return _post_feed({"message": clean_message})


def getPostInfo(post_id):
    config = _config()
    clean_post_id = _clean(post_id)
    if not clean_post_id:
        raise FacebookPublishError("Thiếu Facebook post_id.")

    url = _graph_url(config, clean_post_id)
    LOGGER.info("Facebook get post info post_id=%s page_id=%s", clean_post_id, config["page_id"])
    response = requests.get(
        url,
        params={
            "fields": "id,message,created_time,permalink_url",
            "access_token": config["access_token"],
        },
        timeout=30,
    )
    payload_json = _raise_for_api_error(response)
    LOGGER.info("Facebook post info response post_id=%s response=%s", clean_post_id, payload_json)
    return payload_json


build_facebook_caption = buildFacebookCaption
publish_link_post = publishLinkPost
publish_multi_photo_post = publishMultiPhotoPost
publish_photo_post = publishPhotoPost
publish_text_post = publishTextPost
get_post_info = getPostInfo
resolve_poster_image = resolvePosterImage
