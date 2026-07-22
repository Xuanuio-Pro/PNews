import re
from datetime import datetime
from urllib.parse import urlparse


DEFAULT_MAIN_INTRO = (
    "Tổng hợp những tin tức nổi bật về khoa học, công nghệ, "
    "giáo dục và chuyển đổi số."
)
DEFAULT_SUMMARY_LIMIT = 400


def normalize_text(value):
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    output = []
    blank = False
    for line in lines:
        if not line:
            if output and not blank:
                output.append("")
            blank = True
            continue
        output.append(line)
        blank = False
    return "\n".join(output).strip()


def compact_text(value):
    return " ".join(normalize_text(value).split())


def truncate_summary(value, max_chars=DEFAULT_SUMMARY_LIMIT):
    summary = compact_text(value)
    if len(summary) <= max_chars:
        return summary
    clipped = summary[: max(1, max_chars - 1)].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(".,;: ") + "…"


def is_http_url(value):
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def buildFacebookMainCaption(updated_at=None, intro=DEFAULT_MAIN_INTRO):
    timestamp = updated_at if isinstance(updated_at, datetime) else datetime.now()
    return normalize_text(
        "\n".join(
            [
                "TIN TỨC MỚI TỪ PNEWS",
                f"Cập nhật ngày {timestamp.strftime('%d/%m/%Y')} lúc {timestamp.strftime('%H:%M')}",
                "",
                compact_text(intro) or DEFAULT_MAIN_INTRO,
                "",
                "👉 Bấm vào từng ảnh để xem nội dung chi tiết.",
            ]
        )
    )


def buildFacebookPhotoCaption(article, order=1, summary_limit=DEFAULT_SUMMARY_LIMIT):
    title = compact_text(_value(article, "title"))
    if not title:
        raise ValueError("Mỗi ảnh Facebook phải có title.")
    summary = truncate_summary(_value(article, "summary"), summary_limit)
    source_name = compact_text(_value(article, "sourceName") or _value(article, "source")) or "PNews"
    source_url = compact_text(_value(article, "sourceUrl") or _value(article, "url"))
    if source_url and not is_http_url(source_url):
        raise ValueError("sourceUrl phải là URL HTTP hoặc HTTPS hợp lệ.")

    parts = [f"{int(order)}. {title}"]
    if summary and compact_text(summary).casefold() != title.casefold():
        parts.extend(["", summary])
    parts.extend(["", f"Nguồn: {source_name}"])
    if source_url:
        parts.append(f"🔗 Xem chi tiết: {source_url}")
    return normalize_text("\n".join(parts))


def _value(article, key, default=""):
    if isinstance(article, dict):
        return article.get(key, default)
    try:
        return article[key]
    except (KeyError, IndexError, TypeError):
        return getattr(article, key, default)


build_facebook_main_caption = buildFacebookMainCaption
build_facebook_photo_caption = buildFacebookPhotoCaption
