import json
import logging
import re
from collections import Counter
from time import sleep

import requests
from bs4 import BeautifulSoup

from crawlers.base import HEADERS, clean_text
from config.settings import DATA_DIR
from services.config import get_config_value, get_int_config_value


LOGGER = logging.getLogger(__name__)

SUMMARY_CACHE_PATH = DATA_DIR / "summaries" / "summary_cache.json"
REQUEST_TIMEOUT = get_int_config_value("SUMMARY_REQUEST_TIMEOUT", 25)
MIN_SUMMARY_LENGTH = get_int_config_value("MIN_SUMMARY_LENGTH", 30)
MAX_CONTENT_CHARS = get_int_config_value("MAX_CONTENT_CHARS", 6000)
API_RETRY_ATTEMPTS = get_int_config_value("API_RETRY_ATTEMPTS", 3)
API_RETRY_DELAY_SECONDS = get_int_config_value("API_RETRY_DELAY_SECONDS", 2)
PROVIDER_DISABLE_AFTER_FAILURES = get_int_config_value("PROVIDER_DISABLE_AFTER_FAILURES", 3)
AI_UPGRADEABLE_SOURCES = {"fallback", "missing_content", "pending"}

GEMINI_MODEL = get_config_value("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL = get_config_value("GROQ_MODEL", "llama-3.1-8b-instant")

session = requests.Session()
session.headers.update(HEADERS)
provider_failures = Counter()
disabled_providers = set()


def enrich_missing_summaries(articles, max_missing=None, force_ai=False):
    """Fill missing summaries using article content and AI/fallback summarizers."""
    cache = _load_summary_cache()
    enriched_articles = []
    stats = Counter()
    processed_missing = 0

    for article in articles:
        article = dict(article)
        url = article.get("url", "")
        summary = clean_text(article.get("summary", ""))
        summary_source = article.get("summary_source", "")
        should_upgrade = force_ai and summary_source in AI_UPGRADEABLE_SOURCES

        if _has_summary(summary) and not should_upgrade:
            article["summary"] = summary
            if not article.get("summary_source"):
                article["summary_source"] = "crawler"
            stats[article["summary_source"]] += 1
            enriched_articles.append(article)
            continue

        cached_summary_source = cache.get(url, {}).get("summary_source", "")
        should_use_cache = url in cache and not (
            force_ai and cached_summary_source in AI_UPGRADEABLE_SOURCES
        )

        if should_use_cache:
            article["summary"] = cache[url]["summary"]
            article["summary_source"] = cache[url].get("summary_source", "cache")
            stats[article["summary_source"]] += 1
            enriched_articles.append(article)
            continue

        if max_missing is not None and processed_missing >= max_missing:
            article["summary"] = summary
            if not article.get("summary_source"):
                article["summary_source"] = "pending"
            stats["pending"] += 1
            enriched_articles.append(article)
            continue

        processed_missing += 1
        LOGGER.info(
            "Enrich summary %s%s: %s",
            processed_missing,
            f"/{max_missing}" if max_missing is not None else "",
            article.get("title", "")[:90],
        )

        content = fetch_article_content(url, article.get("source", ""))
        generated_summary, source = summarize_article(
            title=article.get("title", ""),
            content=content,
        )

        article["summary"] = generated_summary
        article["summary_source"] = source
        stats[source] += 1

        if generated_summary:
            cache[url] = {
                "summary": generated_summary,
                "summary_source": source,
            }
            _save_summary_cache(cache)

        enriched_articles.append(article)

    _print_enrichment_stats(stats)
    return enriched_articles


def fetch_article_content(url, source=""):
    if not url:
        return ""

    try:
        response = _get_with_retry(url)
        response.encoding = response.apparent_encoding or "utf-8"
    except requests.RequestException as exc:
        LOGGER.warning("Không tải được nội dung bài viết %s: %s", url, exc)
        return ""

    return extract_article_text(response.text, source)


def extract_article_text(html, source=""):
    soup = BeautifulSoup(html, "lxml")

    for selector in [
        "script",
        "style",
        "noscript",
        "iframe",
        ".RelatedNews",
        ".box-tinlienquan",
        ".article-relate",
        ".ads",
        ".advertisement",
    ]:
        for tag in soup.select(selector):
            tag.decompose()

    source_lower = (source or "").lower()
    selectors = _content_selectors(source_lower)
    paragraphs = []

    for selector in selectors:
        container = soup.select_one(selector)

        if not container:
            continue

        paragraphs = [
            clean_text(paragraph.get_text(" ", strip=True))
            for paragraph in container.select("p")
        ]
        paragraphs = _filter_paragraphs(paragraphs)

        if paragraphs:
            break

    if not paragraphs:
        paragraphs = _filter_paragraphs([
            clean_text(paragraph.get_text(" ", strip=True))
            for paragraph in soup.select("p")
        ])

    return "\n".join(paragraphs)[:MAX_CONTENT_CHARS]


def summarize_article(title, content):
    if not content:
        return "", "missing_content"

    summary = summarize_with_gemini(title, content)

    if summary:
        return summary, "gemini"

    summary = summarize_with_groq(title, content)

    if summary:
        return summary, "groq"

    return fallback_summary(content), "fallback"


def summarize_with_gemini(title, content):
    if _is_provider_disabled("gemini"):
        return ""

    api_key = get_config_value("GEMINI_API_KEY")

    if not api_key:
        return ""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )
    prompt = _summary_prompt(title, content)
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 120,
        },
    }

    try:
        response = _post_json_with_retry(
            "Gemini",
            url,
            params={"key": api_key},
            json_payload=payload,
        )
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        _record_provider_success("gemini")
        return _normalize_summary(text)
    except Exception as exc:
        _record_provider_failure("gemini", exc)
        LOGGER.warning("Gemini summary lỗi: %s", _safe_error_message(exc))
        return ""


def summarize_with_groq(title, content):
    if _is_provider_disabled("groq"):
        return ""

    api_key = get_config_value("GROQ_API_KEY")

    if not api_key:
        return ""

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "Bạn là biên tập viên tin tức. Viết tóm tắt tiếng Việt ngắn, rõ, trung lập.",
            },
            {
                "role": "user",
                "content": _summary_prompt(title, content),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 120,
    }

    try:
        response = _post_json_with_retry(
            "Groq",
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json_payload=payload,
        )
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        _record_provider_success("groq")
        return _normalize_summary(text)
    except Exception as exc:
        _record_provider_failure("groq", exc)
        LOGGER.warning("Groq summary lỗi: %s", _safe_error_message(exc))
        return ""


def fallback_summary(content):
    sentences = re.split(r"(?<=[.!?])\s+", clean_text(content))
    summary = " ".join(sentences[:2])
    return _normalize_summary(summary)


def _summary_prompt(title, content):
    return (
        "Tóm tắt bài báo dưới đây bằng tiếng Việt trong 1-2 câu, tối đa 45 từ. "
        "Không thêm nhận định, không dùng bullet, không nhắc lại tiêu đề nếu không cần.\n\n"
        f"Tiêu đề: {title}\n\n"
        f"Nội dung:\n{content[:MAX_CONTENT_CHARS]}"
    )


def _normalize_summary(text):
    text = clean_text(text)
    text = text.strip("\"' ")
    return text[:450]


def _has_summary(summary):
    return len(clean_text(summary)) >= MIN_SUMMARY_LENGTH


def _is_provider_disabled(provider):
    return provider in disabled_providers


def _record_provider_success(provider):
    provider_failures[provider] = 0


def _record_provider_failure(provider, exc):
    provider_failures[provider] += 1

    if _is_rate_limited_error(exc):
        disabled_providers.add(provider)
        LOGGER.warning(
            "Tạm bỏ qua %s trong lần chạy này do bị rate limit: %s",
            provider,
            _safe_error_message(exc),
        )
        return

    if provider_failures[provider] >= PROVIDER_DISABLE_AFTER_FAILURES:
        disabled_providers.add(provider)
        LOGGER.warning(
            "Tạm bỏ qua %s trong lần chạy này sau %s lỗi liên tiếp: %s",
            provider,
            provider_failures[provider],
            _safe_error_message(exc),
        )


def _post_json_with_retry(provider, url, params=None, headers=None, json_payload=None):
    last_error = None

    for attempt in range(1, API_RETRY_ATTEMPTS + 1):
        try:
            response = session.post(
                url,
                params=params,
                headers=headers,
                json=json_payload,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 429:
                raise requests.HTTPError(
                    f"{response.status_code} {response.reason}",
                    response=response,
                )

            if response.status_code in {500, 502, 503, 504}:
                raise requests.HTTPError(
                    f"{response.status_code} {response.reason}",
                    response=response,
                )

            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc

            if attempt == API_RETRY_ATTEMPTS or not _is_retryable_error(exc):
                raise

            if _is_rate_limited_error(exc):
                raise

            LOGGER.warning(
                "%s tạm lỗi (%s), thử lại %s/%s...",
                provider,
                _safe_error_message(exc),
                attempt + 1,
                API_RETRY_ATTEMPTS,
            )
            sleep(API_RETRY_DELAY_SECONDS * attempt)

    raise last_error


def _get_with_retry(url):
    last_error = None

    for attempt in range(1, API_RETRY_ATTEMPTS + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)

            if response.status_code in {429, 500, 502, 503, 504}:
                raise requests.HTTPError(
                    f"{response.status_code} {response.reason}",
                    response=response,
                )

            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc

            if attempt == API_RETRY_ATTEMPTS or not _is_retryable_error(exc):
                raise

            LOGGER.warning(
                "Tạm lỗi khi tải nội dung bài viết (%s), thử lại %s/%s...",
                _safe_error_message(exc),
                attempt + 1,
                API_RETRY_ATTEMPTS,
            )
            sleep(API_RETRY_DELAY_SECONDS * attempt)

    raise last_error


def _is_retryable_error(exc):
    response = getattr(exc, "response", None)

    if response is None:
        return isinstance(exc, (requests.ConnectionError, requests.Timeout))

    return response.status_code in {429, 500, 502, 503, 504}


def _is_rate_limited_error(exc):
    response = getattr(exc, "response", None)
    return response is not None and response.status_code == 429


def _safe_error_message(exc):
    response = getattr(exc, "response", None)

    if response is not None:
        return f"HTTP {response.status_code} {response.reason}"

    return str(exc)


def _print_enrichment_stats(stats):
    total = sum(stats.values())
    details = ", ".join(
        f"{source}={count}"
        for source, count in sorted(stats.items())
    )
    LOGGER.info("Summary enrichment: total=%s; %s", total, details)


def _content_selectors(source_lower):
    if "vnexpress" in source_lower:
        return [
            "article.fck_detail",
            ".fck_detail",
            ".sidebar-1",
        ]

    if "báo chính phủ" in source_lower or "baochinhphu" in source_lower:
        return [
            ".detail-content",
            ".detail-news",
            ".content-news-detail",
            ".news-detail",
            "article",
            "main",
        ]

    if "ptit" in source_lower:
        return [
            ".entry-content",
            ".post-content",
            ".elementor-widget-theme-post-content",
            "article",
            "main",
        ]

    if "dân trí" in source_lower or "dantri" in source_lower:
        return [
            ".singular-content",
            ".article-body",
            "article",
        ]

    if "24h" in source_lower:
        return [
            ".cate-24h-foot-arti-deta-info",
            ".baiviet-container",
            ".text-conent",
            "article",
        ]

    return ["article", ".article-body", ".content", "main"]


def _filter_paragraphs(paragraphs):
    ignored_prefixes = (
        "Theo dõi",
        "Nguồn:",
        "Ảnh:",
        "Video:",
        "Đọc thêm",
        "Tin liên quan",
    )
    result = []

    for paragraph in paragraphs:
        if len(paragraph) < 40:
            continue
        if paragraph.startswith(ignored_prefixes):
            continue
        result.append(paragraph)

    return result


def _load_summary_cache():
    if not SUMMARY_CACHE_PATH.exists():
        return {}

    try:
        with SUMMARY_CACHE_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_summary_cache(cache):
    SUMMARY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with SUMMARY_CACHE_PATH.open("w", encoding="utf-8") as file:
        json.dump(cache, file, ensure_ascii=False, indent=2)
