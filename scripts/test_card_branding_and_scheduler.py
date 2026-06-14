import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("PNEWS_CRAWLER_RUN_ON_START", "")

from scripts import crawler_scheduler  # noqa: E402
from services.image_generator import generate_news_card  # noqa: E402


class SchedulerBehaviorTest(unittest.TestCase):
    def test_scheduler_waits_for_next_scheduled_run_by_default(self):
        self.assertFalse(crawler_scheduler.RUN_ON_START)


class NewsCardBrandingTest(unittest.TestCase):
    def test_generated_card_has_ptit_logo_in_top_left(self):
        article = {
            "source": "PTIT",
            "title": "Sinh vien PTIT dat giai cao trong cuoc thi AI toan quoc",
            "url": "https://example.com/pnews-demo",
            "thumbnail": "",
            "summary": "Thong tin noi bat ve hoat dong hoc tap, nghien cuu va doi moi sang tao.",
            "category": "Giao duc",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(generate_news_card(article, temp_dir))
            self.assertTrue(output_path.exists())

            image = Image.open(output_path).convert("RGB")
            expected_logo = Image.open(BASE_DIR / "ptit-logo.jpg").convert("RGB")
            expected_logo = expected_logo.resize((136, 136), Image.Resampling.LANCZOS)
            logo_region = image.crop((26, 24, 162, 160))

            self.assertLess(_mean_abs_difference(logo_region, expected_logo), 32)


def _mean_abs_difference(first, second):
    first_pixels = list(_image_pixels(first))
    second_pixels = list(_image_pixels(second))
    total = 0
    count = min(len(first_pixels), len(second_pixels))

    for left, right in zip(first_pixels[:count], second_pixels[:count]):
        total += sum(abs(left[index] - right[index]) for index in range(3)) / 3

    return total / max(count, 1)


def _image_pixels(image):
    if hasattr(image, "get_flattened_data"):
        return image.get_flattened_data()
    return image.getdata()


if __name__ == "__main__":
    unittest.main()
