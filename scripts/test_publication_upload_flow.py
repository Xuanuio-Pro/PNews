import io
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from PIL import Image


BASE_DIR = Path(__file__).resolve().parents[1]

import sys

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import web_app  # noqa: E402


class ClosingConnection(sqlite3.Connection):
    """Make ``with connect_db()`` close its connection for isolated tests."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class PublicationUploadFlowTests(unittest.TestCase):
    """Regression checks for upload -> review -> client publication."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime_dir = Path(self.tempdir.name)
        self.original_paths = {
            "BASE_DIR": web_app.BASE_DIR,
            "DATA_DIR": web_app.DATA_DIR,
            "DB_PATH": web_app.DB_PATH,
            "UPLOAD_DIR": web_app.UPLOAD_DIR,
        }
        web_app.BASE_DIR = self.runtime_dir
        web_app.DATA_DIR = self.runtime_dir / "data"
        web_app.DB_PATH = web_app.DATA_DIR / "cms.sqlite3"
        web_app.UPLOAD_DIR = web_app.DATA_DIR / "uploads"
        self.connect_db_patcher = patch.object(
            web_app,
            "connect_db",
            side_effect=self.connect_test_db,
        )
        self.connect_db_patcher.start()

        # Keep this flow isolated from runtime chat logs and CSV seed data.
        with (
            patch.object(web_app, "init_chat_logs", return_value=None),
            patch.object(web_app, "seed_articles_from_csv", return_value=None),
        ):
            web_app.init_db()

    def tearDown(self):
        self.connect_db_patcher.stop()
        for name, value in self.original_paths.items():
            setattr(web_app, name, value)
        self.tempdir.cleanup()

    def connect_test_db(self):
        web_app.DATA_DIR.mkdir(parents=True, exist_ok=True)
        web_app.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            web_app.DB_PATH,
            timeout=30,
            factory=ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def make_png_file_part(filename="an-pham-test.png"):
        buffer = io.BytesIO()
        Image.new("RGB", (320, 180), (188, 0, 45)).save(buffer, format="PNG")
        return {"filename": filename, "content": buffer.getvalue()}

    def test_upload_review_and_client_visibility(self):
        fields = {
            "title": "Ấn phẩm kiểm thử sau cập nhật",
            "summary": "Nội dung dùng để kiểm tra luồng upload và duyệt.",
            "source": "PNews QA",
            "url": "https://example.com/an-pham-qa",
            "content_topic": "Khoa học - Công nghệ",
            "category": "Khoa học - Công nghệ",
        }

        article_id, status = web_app.create_uploaded_article(
            fields,
            self.make_png_file_part(),
        )

        self.assertEqual(status, "pending")
        pending_article = web_app.get_article(article_id)
        self.assertIsNotNone(pending_article)
        self.assertEqual(pending_article["status"], "pending")
        self.assertEqual(pending_article["approval_status"], "pending")
        self.assertEqual(
            pending_article["image_path"],
            pending_article["generated_poster_image"],
        )
        self.assertEqual(web_app.count_articles(status="approved"), 0)

        stored_image = self.runtime_dir / pending_article["image_path"]
        self.assertTrue(stored_image.is_file())
        with Image.open(stored_image) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (320, 180))

        web_app.set_article_status(article_id, "approved")
        approved_articles = web_app.query_articles(status="approved")

        self.assertEqual([row["id"] for row in approved_articles], [article_id])
        approved_article = approved_articles[0]
        self.assertEqual(approved_article["approval_status"], "approved")
        self.assertTrue(approved_article["approved_at"])

        client_card = web_app.render_client_card(approved_article)
        self.assertIn(fields["title"], client_card)
        self.assertIn(fields["summary"], client_card)
        self.assertIn("/media/data/uploads/", client_card)

    def test_upload_rejects_missing_title_and_unsupported_file(self):
        with self.assertRaisesRegex(ValueError, "tiêu đề"):
            web_app.create_uploaded_article(
                {"title": "   "},
                self.make_png_file_part(),
            )

        with self.assertRaisesRegex(ValueError, "JPG, PNG, WEBP hoặc GIF"):
            web_app.create_uploaded_article(
                {"title": "Ấn phẩm sai định dạng"},
                {"filename": "an-pham.txt", "content": b"not-an-image"},
            )

        self.assertEqual(web_app.count_articles(), 0)

    def test_twelve_facebook_articles_are_split_into_safe_batches(self):
        article_ids = []
        for index in range(12):
            article_id, status = web_app.create_uploaded_article(
                {
                    "title": f"Ấn phẩm Facebook {index + 1}",
                    "summary": "Tóm tắt kiểm thử đăng Facebook theo nhóm.",
                    "source": "PNews QA",
                    "url": f"https://example.com/facebook-{index + 1}",
                    "publish_now": "on",
                },
                self.make_png_file_part(f"facebook-{index + 1}.png"),
            )
            self.assertEqual(status, "approved")
            article_ids.append(article_id)

        published_sizes = []

        def fake_publish(articles, image_paths, **_kwargs):
            published_sizes.append(len(articles))
            post_id = f"page_post-{len(published_sizes)}"
            return SimpleNamespace(
                dry_run=False,
                facebook_post_id=post_id,
            ), {"id": post_id}

        with (
            patch.object(web_app, "publishFacebookNewsBatch", side_effect=fake_publish),
            patch.object(web_app.FacebookApiClient, "from_env", return_value=object()),
            patch.object(web_app, "getPostInfo", return_value={"permalink_url": "https://facebook.test/post"}),
            patch.object(web_app.time, "sleep", return_value=None),
        ):
            result = web_app.publish_articles_to_facebook_bulk(article_ids)

        self.assertTrue(result["success"])
        self.assertEqual(result["post_count"], 2)
        self.assertEqual(result["batch_count"], 2)
        self.assertEqual(published_sizes, [10, 2])
        self.assertEqual(
            sum(1 for item in result["results"] if item["status"] == "success"),
            12,
        )

    def test_facebook_summary_includes_first_real_error(self):
        summary = web_app.summarize_facebook_bulk_result(
            {
                "post_count": 0,
                "results": [
                    {"article_id": 1, "status": "failed", "error": "Invalid OAuth token (code=190)"},
                    {"article_id": 2, "status": "failed", "error": "Invalid OAuth token (code=190)"},
                ],
            }
        )

        self.assertIn("lỗi 2", summary)
        self.assertIn("Invalid OAuth token (code=190)", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
