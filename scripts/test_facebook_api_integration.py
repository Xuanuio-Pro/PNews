import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from services.facebook_api_client import FacebookApiClient
from services.facebook_models import FacebookPublicationRepository
from services.facebook_publisher import FacebookPublicationError, publishFacebookNewsBatch


class MockGraphHandler(BaseHTTPRequestHandler):
    state = {}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.path.endswith("/photos"):
            self._handle_photo(body)
            return
        if self.path.endswith("/feed"):
            self.state["feed_requests"] += 1
            self.state["feed_bodies"].append(body.decode("utf-8", errors="replace"))
            if self.state["scenario"] == "feed_failure":
                self._json(500, {"error": {"message": "feed unavailable", "code": 2}})
                return
            self._json(200, {"id": "mock-page_mock-post"})
            return
        self._json(404, {"error": {"message": "not found", "code": 100}})

    def _handle_photo(self, body):
        self.state["photo_requests"] += 1
        self.state["photo_bodies"].append(body)
        scenario = self.state["scenario"]
        request_number = self.state["photo_requests"]
        if scenario == "retry_second_once" and request_number == 2:
            self._json(500, {"error": {"message": "temporary", "code": 2}})
            return
        if scenario == "permanent_second" and b"2. Ti" in body:
            self._json(500, {"error": {"message": "permanent test failure", "code": 2}})
            return
        if scenario == "rate_limit_once" and request_number == 1:
            self._json(429, {"error": {"message": "rate limit", "code": 4}})
            return
        if scenario == "invalid_token":
            self._json(400, {"error": {"message": "Invalid OAuth token", "code": 190}})
            return
        self.state["photo_successes"] += 1
        self._json(200, {"id": f"mock-photo-{self.state['photo_successes']}"})

    def _json(self, status, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format, *_args):
        return


class FacebookMockHttpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MockGraphHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.base_url = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        MockGraphHandler.state = {
            "scenario": "success",
            "photo_requests": 0,
            "photo_successes": 0,
            "feed_requests": 0,
            "photo_bodies": [],
            "feed_bodies": [],
        }
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = FacebookPublicationRepository(Path(self.tempdir.name) / "db.sqlite3")
        self.articles = []
        self.images = []
        for index in range(1, 4):
            image = Path(self.tempdir.name) / f"image-{index}.jpg"
            image.write_bytes(f"image-{index}".encode())
            self.images.append(str(image))
            self.articles.append(
                {
                    "id": index,
                    "title": f"Tiêu đề {index}",
                    "summary": f"Tóm tắt {index}",
                    "source": "PNews",
                    "url": f"https://example.com/{index}",
                }
            )

    def tearDown(self):
        self.tempdir.cleanup()

    def client(self, retries=1):
        return FacebookApiClient(
            "mock-page",
            "mock-token",
            graph_api_version="v25.0",
            timeout_ms=2000,
            max_retries=retries,
            base_url=self.base_url,
        )

    @patch("services.facebook_api_client.time.sleep", return_value=None)
    def test_three_photos_second_fails_once_then_one_post(self, _sleep):
        MockGraphHandler.state["scenario"] = "retry_second_once"
        publication, _ = publishFacebookNewsBatch(
            self.articles,
            self.images,
            batch_id="integration-retry",
            client=self.client(retries=2),
            repository=self.repository,
            concurrency=1,
        )
        self.assertEqual(publication.status, "PUBLISHED")
        self.assertEqual(MockGraphHandler.state["photo_requests"], 4)
        self.assertEqual(MockGraphHandler.state["feed_requests"], 1)
        feed_body = MockGraphHandler.state["feed_bodies"][0]
        self.assertLess(feed_body.index("attached_media%5B0%5D"), feed_body.index("attached_media%5B1%5D"))

    @patch("services.facebook_api_client.time.sleep", return_value=None)
    def test_one_photo_fails_completely_abort(self, _sleep):
        MockGraphHandler.state["scenario"] = "permanent_second"
        with self.assertRaises(FacebookPublicationError):
            publishFacebookNewsBatch(
                self.articles,
                self.images,
                batch_id="integration-photo-fail",
                client=self.client(retries=1),
                repository=self.repository,
                concurrency=1,
                partial_policy="abort",
            )
        self.assertEqual(MockGraphHandler.state["feed_requests"], 0)

    @patch("services.facebook_api_client.time.sleep", return_value=None)
    def test_feed_failure_marks_publication_failed(self, _sleep):
        MockGraphHandler.state["scenario"] = "feed_failure"
        with self.assertRaises(Exception):
            publishFacebookNewsBatch(
                self.articles,
                self.images,
                batch_id="integration-feed-fail",
                client=self.client(retries=1),
                repository=self.repository,
                concurrency=1,
            )
        stored = self.repository.get_by_idempotency_key(
            "facebook-publication:mock-page:" + __import__("datetime").date.today().isoformat() + ":integration-feed-fail"
        )
        self.assertEqual(stored.status, "FAILED")

    @patch("services.facebook_api_client.time.sleep", return_value=None)
    def test_rate_limit_is_retried(self, _sleep):
        MockGraphHandler.state["scenario"] = "rate_limit_once"
        publication, _ = publishFacebookNewsBatch(
            self.articles,
            self.images,
            batch_id="integration-rate",
            client=self.client(retries=1),
            repository=self.repository,
            concurrency=1,
        )
        self.assertEqual(publication.status, "PUBLISHED")
        self.assertEqual(MockGraphHandler.state["photo_requests"], 4)

    @patch("services.facebook_api_client.time.sleep", return_value=None)
    def test_access_token_error_is_not_retried(self, _sleep):
        MockGraphHandler.state["scenario"] = "invalid_token"
        with self.assertRaises(FacebookPublicationError):
            publishFacebookNewsBatch(
                self.articles,
                self.images,
                batch_id="integration-token",
                client=self.client(retries=3),
                repository=self.repository,
                concurrency=1,
                partial_policy="abort",
            )
        self.assertEqual(MockGraphHandler.state["photo_requests"], 3)
        self.assertEqual(MockGraphHandler.state["feed_requests"], 0)


if __name__ == "__main__":
    unittest.main()
