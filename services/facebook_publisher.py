import hashlib
import logging
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from config.settings import DATA_DIR, DATABASE_PATH
from services.config import get_config_value, get_int_config_value
from services.facebook_api_client import (
    FacebookApiClient,
    FacebookApiClientError,
    FacebookPublishUncertainError,
)
from services.facebook_captions import (
    buildFacebookMainCaption,
    buildFacebookPhotoCaption,
    is_http_url,
    normalize_text,
)
from services.facebook_models import (
    FacebookMediaItem,
    FacebookPublicationRepository,
    build_idempotency_key,
    new_publication,
    now_iso,
)


LOGGER = logging.getLogger(__name__)
PARTIAL_POLICIES = {"abort", "skip_failed"}


class FacebookPublicationError(Exception):
    pass


def build_media_items(articles, image_paths):
    if len(articles or []) != len(image_paths or []):
        raise ValueError("Số article và image path không khớp.")
    items = []
    for order, (article, image_path) in enumerate(zip(articles, image_paths), start=1):
        article_id = int(_value(article, "id"))
        value = str(image_path or "").strip()
        image_url = value if is_http_url(value) else ""
        local_image_path = "" if image_url else value
        item = FacebookMediaItem(
            order=order,
            article_id=article_id,
            title=str(_value(article, "title") or "").strip(),
            summary=str(_value(article, "summary") or "").strip(),
            source_name=str(_value(article, "source") or "").strip(),
            source_url=str(_value(article, "url") or "").strip(),
            image_url=image_url,
            local_image_path=local_image_path,
        )
        item.photo_caption = buildFacebookPhotoCaption(article, order=order)
        items.append(item)
    validate_media_items(items)
    return items


def validate_media_items(media_items):
    if not media_items:
        raise ValueError("Publication phải có ít nhất một media item.")
    seen_article_ids = set()
    seen_orders = set()
    for item in media_items:
        if item.article_id in seen_article_ids:
            raise ValueError(f"articleId bị trùng trong batch: {item.article_id}")
        if item.order in seen_orders:
            raise ValueError(f"order bị trùng trong batch: {item.order}")
        seen_article_ids.add(item.article_id)
        seen_orders.add(item.order)
        if not str(item.title or "").strip():
            raise ValueError(f"articleId={item.article_id} thiếu title.")
        if not item.image_url and not item.local_image_path:
            raise ValueError(f"articleId={item.article_id} thiếu ảnh.")
        if not is_http_url(item.source_url):
            raise ValueError(f"articleId={item.article_id} có sourceUrl không hợp lệ.")
    media_items.sort(key=lambda item: item.order)


def uploadUnpublishedFacebookPhoto(client, item, publication_id=""):
    return client.uploadUnpublishedFacebookPhoto(item, publication_id=publication_id)


def uploadFacebookPhotos(
    publication,
    client,
    repository,
    concurrency=3,
    partial_policy="abort",
):
    policy = str(partial_policy or "abort").strip().lower()
    if policy not in PARTIAL_POLICIES:
        raise ValueError("FACEBOOK_PARTIAL_POST_POLICY phải là abort hoặc skip_failed.")
    repository.update_publication(publication.id, status="PHOTOS_UPLOADING", last_error="")
    pending = [item for item in publication.media_items if not item.facebook_photo_id]
    for item in publication.media_items:
        if item.facebook_photo_id:
            item.upload_status = "UPLOADED"

    def worker(item):
        repository.update_media(
            publication.id,
            item.article_id,
            upload_status="UPLOADING",
            upload_error="",
        )
        try:
            response = uploadUnpublishedFacebookPhoto(client, item, publication.id)
            photo_id = str(response.get("id") or "").strip()
            if not photo_id:
                raise FacebookPublicationError("Facebook API không trả về photo ID.")
            repository.update_media(
                publication.id,
                item.article_id,
                facebook_photo_id=photo_id,
                upload_status="UPLOADED",
                upload_error="",
            )
            LOGGER.info(
                "publicationId=%s articleId=%s event=facebook_photo_uploaded photoId=%s",
                publication.id,
                item.article_id,
                photo_id,
            )
            return item.article_id, photo_id, ""
        except Exception as exc:
            error = _safe_error(exc)
            repository.update_media(
                publication.id,
                item.article_id,
                upload_status="FAILED",
                upload_error=error,
            )
            LOGGER.error(
                "publicationId=%s articleId=%s event=facebook_photo_failed error=%s",
                publication.id,
                item.article_id,
                error,
            )
            return item.article_id, "", error

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as executor:
            futures = [executor.submit(worker, item) for item in pending]
            for future in as_completed(futures):
                article_id, photo_id, error = future.result()
                item = next(media for media in publication.media_items if media.article_id == article_id)
                item.facebook_photo_id = photo_id
                item.upload_status = "UPLOADED" if photo_id else "FAILED"
                item.upload_error = error

    uploaded = [item for item in publication.media_items if item.facebook_photo_id]
    failed = [item for item in publication.media_items if not item.facebook_photo_id]
    if failed:
        status = "FAILED" if policy == "abort" else "PARTIAL_FAILED"
        repository.update_publication(
            publication.id,
            status=status,
            last_error=f"{len(failed)} ảnh upload thất bại.",
        )
    else:
        repository.update_publication(publication.id, status="PHOTOS_UPLOADED", last_error="")
    return uploaded, failed


def createFacebookMultiPhotoPost(publication, client, repository, uploaded_items):
    ordered = sorted(uploaded_items, key=lambda item: item.order)
    media_ids = [item.facebook_photo_id for item in ordered]
    repository.update_publication(publication.id, status="POST_PUBLISHING", last_error="")
    try:
        response = client.createFacebookMultiPhotoPost(
            publication.main_caption,
            media_ids,
            publication_id=publication.id,
        )
    except FacebookPublishUncertainError as exc:
        message = "Feed publish timeout; cần reconcile thủ công trước khi thử lại."
        repository.update_publication(publication.id, status="PARTIAL_FAILED", last_error=message)
        LOGGER.error(
            "publicationId=%s event=facebook_post_outcome_unknown error=%s",
            publication.id,
            message,
        )
        raise FacebookPublicationError(message) from exc
    except Exception as exc:
        message = _safe_error(exc)
        repository.update_publication(publication.id, status="FAILED", last_error=message)
        raise

    post_id = str(response.get("id") or response.get("post_id") or "").strip()
    if not post_id:
        repository.update_publication(
            publication.id,
            status="FAILED",
            last_error="Facebook API không trả về post ID.",
        )
        raise FacebookPublicationError("Facebook API không trả về post ID.")
    published_at = now_iso()
    repository.update_publication(
        publication.id,
        status="PUBLISHED",
        facebook_post_id=post_id,
        published_at=published_at,
        last_error="",
    )
    publication.status = "PUBLISHED"
    publication.facebook_post_id = post_id
    publication.published_at = published_at
    LOGGER.info(
        "publicationId=%s event=facebook_post_published postId=%s",
        publication.id,
        post_id,
    )
    return response


def publishFacebookNewsBatch(
    articles,
    image_paths,
    batch_id=None,
    publication_date=None,
    client=None,
    repository=None,
    main_caption=None,
    partial_policy=None,
    min_photos=None,
    concurrency=None,
    photo_captions=None,
):
    client = client or FacebookApiClient.from_env()
    repository = repository or FacebookPublicationRepository(DATABASE_PATH)
    publication_date = str(publication_date or date.today().isoformat())
    batch_id = str(batch_id or _stable_batch_id(articles))
    if client.dry_run:
        batch_id = f"{batch_id}-dry-run-{uuid.uuid4().hex[:8]}"
    main_caption = normalize_text(main_caption or buildFacebookMainCaption())
    if not main_caption:
        raise ValueError("mainCaption không được rỗng.")
    idempotency_key = build_idempotency_key(client.page_id, publication_date, batch_id)
    existing = repository.get_by_idempotency_key(idempotency_key)
    if existing and existing.status == "PUBLISHED":
        LOGGER.info(
            "publicationId=%s event=facebook_publish_skipped reason=idempotency_published",
            existing.id,
        )
        return existing, {"id": existing.facebook_post_id, "idempotent": True}
    if existing and existing.status == "POST_PUBLISHING":
        raise FacebookPublicationError("Publication đang POST_PUBLISHING; phải reconcile trước khi thử lại.")
    if existing and existing.status == "PARTIAL_FAILED" and "reconcile" in existing.last_error.lower():
        raise FacebookPublicationError(existing.last_error)

    if existing:
        publication = existing
    else:
        media_items = build_media_items(articles, image_paths)
        overrides = photo_captions or {}
        for item in media_items:
            custom_caption = str(
                overrides.get(item.article_id, overrides.get(str(item.article_id), "")) or ""
            ).strip()
            if custom_caption:
                item.photo_caption = normalize_text(custom_caption)
        publication = new_publication(
            client.page_id,
            publication_date,
            batch_id,
            main_caption,
            media_items,
            dry_run=client.dry_run,
        )
        repository.create(publication)

    if client.dry_run:
        preview_path = DATA_DIR / "facebook_previews" / f"{publication.id}.json"
        api_preview = {
            "photoUploads": [
                {
                    "endpoint": f"/{client.page_id}/photos",
                    "published": False,
                    "message": item.photo_caption,
                    "imageUrl": item.image_url,
                    "localImagePath": item.local_image_path,
                    "accessToken": "***",
                }
                for item in publication.media_items
            ],
            "feedPost": {
                "endpoint": f"/{client.page_id}/feed",
                "message": publication.main_caption,
                "attached_media": [
                    {"media_fbid": f"dry-photo-{item.order}"}
                    for item in publication.media_items
                ],
                "accessToken": "***",
            },
        }
        repository.write_preview(publication, preview_path, api_preview=api_preview)
        _safe_print(publication.main_caption)
        for item in publication.media_items:
            _safe_print(f"\n--- Ảnh {item.order} / articleId={item.article_id} ---\n{item.photo_caption}")
        _safe_print("\nPayload preview (token đã che):")
        _safe_print(__import__("json").dumps(api_preview, ensure_ascii=False, indent=2))
        _safe_print(f"\nDry-run preview: {preview_path}")
        return publication, {
            "dry_run": True,
            "preview_path": str(preview_path),
            "api_preview": api_preview,
        }

    policy = str(
        partial_policy or get_config_value("FACEBOOK_PARTIAL_POST_POLICY", "abort")
    ).strip().lower()
    minimum = int(min_photos or get_int_config_value("FACEBOOK_MIN_PHOTOS_TO_PUBLISH", 3))
    workers = int(concurrency or get_int_config_value("FACEBOOK_UPLOAD_CONCURRENCY", 3))
    uploaded, failed = uploadFacebookPhotos(
        publication,
        client,
        repository,
        concurrency=workers,
        partial_policy=policy,
    )
    if failed and policy == "abort":
        raise FacebookPublicationError(f"Hủy publication vì {len(failed)} ảnh upload thất bại.")
    if failed and len(uploaded) < minimum:
        repository.update_publication(
            publication.id,
            status="FAILED",
            last_error=f"Chỉ có {len(uploaded)} ảnh thành công, cần tối thiểu {minimum}.",
        )
        raise FacebookPublicationError(
            f"Không đủ ảnh thành công để đăng: {len(uploaded)}/{minimum}."
        )
    response = createFacebookMultiPhotoPost(publication, client, repository, uploaded)
    return publication, response


def _stable_batch_id(articles):
    article_ids = [str(_value(article, "id")) for article in articles or []]
    raw = ",".join(article_ids)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _value(article, key, default=""):
    if isinstance(article, dict):
        return article.get(key, default)
    try:
        return article[key]
    except (KeyError, IndexError, TypeError):
        return getattr(article, key, default)


def _safe_error(exc):
    if isinstance(exc, FacebookApiClientError):
        details = exc.details
        return f"{details.message} (code={details.code}, http={details.http_status})"[:1000]
    return str(exc)[:1000]


def _safe_print(value):
    text = str(value)
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding))


build_facebook_media_items = build_media_items
upload_unpublished_facebook_photo = uploadUnpublishedFacebookPhoto
upload_facebook_photos = uploadFacebookPhotos
create_facebook_multi_photo_post = createFacebookMultiPhotoPost
publish_facebook_news_batch = publishFacebookNewsBatch
