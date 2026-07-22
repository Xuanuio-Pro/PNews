import tempfile
import unittest
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import requests

from services.facebook_api_client import (
    FacebookApiClient,
    FacebookApiClientError,
    FacebookPublishUncertainError,
)
from services.facebook_captions import (
    buildFacebookMainCaption,
    buildFacebookPhotoCaption,
    normalize_text,
)
from services.facebook_models import FacebookMediaItem, FacebookPublicationRepository
from services.facebook_publisher import FacebookPublicationError, publishFacebookNewsBatch


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = ""
        self.ok = 200 <= status < 300

    def json(self):
        return self._payload


class RecordingSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, data=None, timeout=None):
        self.calls.append((method, url, dict(data or {}), timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, data=None, files=None, timeout=None):
        self.calls.append(("POST", url, dict(data or {}), timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ScenarioClient:
    page_id = "page-test"
    dry_run = False

    def __init__(self, fail_articles=None):
        self.fail_articles = set(fail_articles or [])
        self.upload_calls = []
        self.feed_calls = []

    def uploadUnpublishedFacebookPhoto(self, item, publication_id=""):
        self.upload_calls.append(item.article_id)
        if item.article_id in self.fail_articles:
            raise RuntimeError("upload failed")
        return {"id": f"photo-{item.article_id}"}

    def createFacebookMultiPhotoPost(self, message, media_fbids, publication_id=""):
        self.feed_calls.append(list(media_fbids))
        return {"id": "page-test_post-1"}


def sample_articles(count=3):
    return [
        {
            "id": index,
            "title": f"Tiêu đề {index}",
            "summary": f"Tóm tắt {index}",
            "source": "VNExpress",
            "url": f"https://example.com/{index}",
        }
        for index in range(1, count + 1)
    ]


class CaptionBuilderTests(unittest.TestCase):
    def test_main_caption_is_short_and_contains_required_lines(self):
        caption = buildFacebookMainCaption(datetime(2026, 7, 17, 10, 30))
        self.assertIn("TIN TỨC MỚI TỪ PNEWS", caption)
        self.assertIn("Cập nhật ngày 17/07/2026 lúc 10:30", caption)
        self.assertIn("Bấm vào từng ảnh", caption)
        self.assertNotIn("Nguồn:", caption)

    def test_photo_caption_normalizes_whitespace(self):
        article = {
            "title": "  Tiêu   đề   thử  ",
            "summary": "Tóm   tắt\n\n\n\n có khoảng trắng",
            "source": "  VNExpress ",
            "url": "https://example.com/a",
        }
        caption = buildFacebookPhotoCaption(article, order=2)
        self.assertIn("2. Tiêu đề thử", caption)
        self.assertNotIn("\n\n\n", caption)
        self.assertNotIn("   ", caption)

    def test_long_summary_is_limited(self):
        article = {
            "title": "Tiêu đề",
            "summary": "nội dung " * 100,
            "source": "PNews",
            "url": "https://example.com/a",
        }
        caption = buildFacebookPhotoCaption(article, summary_limit=400)
        summary = caption.split("\n\n")[1]
        self.assertLessEqual(len(summary), 400)
        self.assertTrue(summary.endswith("…"))

    def test_missing_source_name_uses_pnews(self):
        caption = buildFacebookPhotoCaption(
            {"title": "Tin", "summary": "Tóm tắt", "url": "https://example.com"}
        )
        self.assertIn("Nguồn: PNews", caption)

    def test_invalid_source_url_is_rejected(self):
        with self.assertRaises(ValueError):
            buildFacebookPhotoCaption(
                {"title": "Tin", "summary": "Tóm tắt", "url": "javascript:bad"}
            )

    def test_duplicate_title_summary_is_not_repeated(self):
        caption = buildFacebookPhotoCaption(
            {
                "title": "Cùng nội dung",
                "summary": "Cùng nội dung",
                "source": "PNews",
                "url": "https://example.com",
            }
        )
        self.assertEqual(caption.count("Cùng nội dung"), 1)


class ApiClientTests(unittest.TestCase):
    def test_attached_media_order_is_preserved(self):
        session = RecordingSession([FakeResponse(payload={"id": "post"})])
        client = FacebookApiClient("page", "token", session=session, max_retries=0)
        client.createFacebookMultiPhotoPost("main", ["photo-2", "photo-1"])
        payload = session.calls[0][2]
        self.assertIn('"photo-2"', payload["attached_media[0]"])
        self.assertIn('"photo-1"', payload["attached_media[1]"])

    @patch("services.facebook_api_client.time.sleep", return_value=None)
    def test_photo_timeout_is_retried(self, _sleep):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "a.jpg"
            image.write_bytes(b"test")
            session = RecordingSession(
                [requests.Timeout("timeout"), FakeResponse(payload={"id": "photo-ok"})]
            )
            client = FacebookApiClient("page", "token", session=session, max_retries=3)
            item = FacebookMediaItem(
                1, 1, "Tin", "Tóm tắt", "PNews", "https://example.com",
                local_image_path=str(image), photo_caption="caption",
            )
            response = client.uploadUnpublishedFacebookPhoto(item)
            self.assertEqual(response["id"], "photo-ok")
            self.assertEqual(len(session.calls), 2)

    @patch("services.facebook_api_client.time.sleep", return_value=None)
    def test_invalid_token_is_not_retried(self, _sleep):
        error = {"error": {"message": "Invalid OAuth access token", "code": 190}}
        session = RecordingSession([FakeResponse(status=400, payload=error)])
        client = FacebookApiClient("page", "token", session=session, max_retries=3)
        with self.assertRaises(FacebookApiClientError):
            client.createFacebookMultiPhotoPost("main", ["photo"])
        self.assertEqual(len(session.calls), 1)

    def test_public_image_url_is_supported(self):
        session = RecordingSession([FakeResponse(payload={"id": "photo-url"})])
        client = FacebookApiClient("page", "token", session=session, max_retries=0)
        item = FacebookMediaItem(
            1, 1, "Tin", "Tóm tắt", "PNews", "https://example.com/article",
            image_url="https://example.com/image.jpg", photo_caption="caption",
        )
        response = client.uploadUnpublishedFacebookPhoto(item)
        self.assertEqual(response["id"], "photo-url")
        self.assertEqual(session.calls[0][2]["url"], "https://example.com/image.jpg")

    def test_feed_connection_error_is_uncertain_and_not_retried(self):
        session = RecordingSession([requests.ConnectionError("reset")])
        client = FacebookApiClient("page", "token", session=session, max_retries=3)
        with self.assertRaises(FacebookPublishUncertainError):
            client.createFacebookMultiPhotoPost("main", ["photo"])
        self.assertEqual(len(session.calls), 1)


class PublicationFlowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = FacebookPublicationRepository(Path(self.tempdir.name) / "test.sqlite3")
        self.images = []
        for index in range(1, 4):
            path = Path(self.tempdir.name) / f"{index}.jpg"
            path.write_bytes(b"image")
            self.images.append(str(path))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_published_idempotency_key_is_not_posted_twice(self):
        client = ScenarioClient()
        publication, _ = publishFacebookNewsBatch(
            sample_articles(), self.images, client=client, repository=self.repository,
            publication_date="2026-07-22", batch_id="batch-a",
        )
        again, response = publishFacebookNewsBatch(
            sample_articles(), self.images, client=client, repository=self.repository,
            publication_date="2026-07-22", batch_id="batch-a",
        )
        self.assertEqual(publication.id, again.id)
        self.assertTrue(response["idempotent"])
        self.assertEqual(len(client.feed_calls), 1)

    def test_abort_policy_does_not_create_feed(self):
        client = ScenarioClient(fail_articles={2})
        with self.assertRaises(FacebookPublicationError):
            publishFacebookNewsBatch(
                sample_articles(), self.images, client=client, repository=self.repository,
                batch_id="batch-abort", partial_policy="abort", concurrency=1,
            )
        self.assertEqual(client.feed_calls, [])

    def test_skip_failed_posts_when_threshold_is_met(self):
        client = ScenarioClient(fail_articles={2})
        publication, _ = publishFacebookNewsBatch(
            sample_articles(), self.images, client=client, repository=self.repository,
            batch_id="batch-skip", partial_policy="skip_failed", min_photos=2, concurrency=1,
        )
        self.assertEqual(publication.status, "PUBLISHED")
        self.assertEqual(client.feed_calls, [["photo-1", "photo-3"]])

    def test_dry_run_writes_preview_without_api_calls(self):
        client = ScenarioClient()
        client.dry_run = True
        preview_root = Path(self.tempdir.name) / "preview-data"
        with patch("services.facebook_publisher.DATA_DIR", preview_root):
            publication, response = publishFacebookNewsBatch(
                sample_articles(), self.images, client=client, repository=self.repository,
                batch_id="batch-dry", concurrency=1,
            )
        self.assertTrue(response["dry_run"])
        self.assertEqual(client.upload_calls, [])
        self.assertEqual(client.feed_calls, [])
        self.assertTrue(Path(response["preview_path"]).is_file())


class PersistenceMigrationTests(unittest.TestCase):
    def test_additive_schema_keeps_existing_articles(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "existing.sqlite3"
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT)")
                conn.execute("INSERT INTO articles (id, title) VALUES (1, 'Bài cũ')")
                conn.commit()
            FacebookPublicationRepository(database)
            with closing(sqlite3.connect(database)) as conn:
                title = conn.execute("SELECT title FROM articles WHERE id = 1").fetchone()[0]
                tables = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
            self.assertEqual(title, "Bài cũ")
            self.assertIn("facebook_publications", tables)
            self.assertIn("facebook_media_items", tables)


if __name__ == "__main__":
    unittest.main()
