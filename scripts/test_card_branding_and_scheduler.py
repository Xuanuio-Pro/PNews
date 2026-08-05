import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("PNEWS_CRAWLER_RUN_ON_START", "")

from scripts import crawler_scheduler  # noqa: E402
from services.image_generator import (  # noqa: E402
    SUMMARY_FONT_SIZE,
    SUMMARY_LINE_SPACING,
    SUMMARY_MAX_LINES,
    SUMMARY_MAX_WIDTH,
    SUMMARY_MIN_FONT_SIZE,
    TITLE_FONT_SIZE,
    TITLE_LINE_SPACING,
    TITLE_MAX_HEIGHT,
    TITLE_MAX_LINES,
    TITLE_MAX_WIDTH,
    TITLE_MIN_FONT_SIZE,
    _fit_text_to_box,
    _line_height,
    _load_bold_font,
    _load_regular_font,
    _text_width,
    generate_news_card,
)


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
            expected_logo = ImageOps.exif_transpose(Image.open(BASE_DIR / "Logo PTIT.png")).convert("RGBA")
            expected_logo.thumbnail((136, 136), Image.Resampling.LANCZOS)
            logo_slot = Image.new("RGBA", (136, 136), (0, 0, 0, 0))
            offset_x = (136 - expected_logo.width) // 2
            offset_y = (136 - expected_logo.height) // 2
            logo_slot.alpha_composite(expected_logo, (offset_x, offset_y))
            logo_region = image.crop((26, 24, 162, 160)).convert("RGBA")

            self.assertLess(_mean_abs_difference_on_mask(logo_region, logo_slot), 40)

    def test_long_vietnamese_title_is_resized_instead_of_overflowing(self):
        title = (
            "Học viện Công nghệ Bưu chính Viễn thông đóng góp luận cứ khoa học "
            "về đo lường kinh tế số tại Hội nghị chuyên đề của Thành phố Hồ Chí Minh"
        )
        draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350), "white"))

        font, lines = _fit_text_to_box(
            draw=draw,
            text=title,
            font_loader=_load_bold_font,
            max_font_size=TITLE_FONT_SIZE,
            min_font_size=TITLE_MIN_FONT_SIZE,
            max_width=TITLE_MAX_WIDTH,
            max_lines=TITLE_MAX_LINES,
            max_height=TITLE_MAX_HEIGHT,
            line_spacing=TITLE_LINE_SPACING,
        )

        self.assertNotIn("…", " ".join(lines))
        self.assertLessEqual(len(lines), TITLE_MAX_LINES)
        self.assertTrue(all(_text_width(draw, line, font) <= TITLE_MAX_WIDTH for line in lines))
        self.assertLessEqual(
            len(lines) * (_line_height(draw, font) + TITLE_LINE_SPACING),
            TITLE_MAX_HEIGHT,
        )

    def test_long_summary_is_clipped_inside_available_height(self):
        summary = " ".join(["Nội dung bài viết cần được trình bày rõ ràng và cân đối."] * 20)
        max_height = 230
        draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350), "white"))

        font, lines = _fit_text_to_box(
            draw=draw,
            text=summary,
            font_loader=_load_regular_font,
            max_font_size=SUMMARY_FONT_SIZE,
            min_font_size=SUMMARY_MIN_FONT_SIZE,
            max_width=SUMMARY_MAX_WIDTH,
            max_lines=SUMMARY_MAX_LINES,
            max_height=max_height,
            line_spacing=SUMMARY_LINE_SPACING,
        )

        self.assertLessEqual(len(lines), SUMMARY_MAX_LINES)
        self.assertTrue(lines[-1].endswith("…"))
        self.assertTrue(all(_text_width(draw, line, font) <= SUMMARY_MAX_WIDTH for line in lines))
        self.assertLessEqual(
            len(lines) * (_line_height(draw, font) + SUMMARY_LINE_SPACING),
            max_height,
        )


def _mean_abs_difference(first, second):
    first_pixels = list(_image_pixels(first))
    second_pixels = list(_image_pixels(second))
    total = 0
    count = min(len(first_pixels), len(second_pixels))

    for left, right in zip(first_pixels[:count], second_pixels[:count]):
        total += sum(abs(left[index] - right[index]) for index in range(3)) / 3

    return total / max(count, 1)


def _mean_abs_difference_on_mask(actual, expected, alpha_threshold=24):
    actual_pixels = list(actual.getdata())
    expected_pixels = list(expected.getdata())
    total = 0
    count = 0

    for actual_pixel, expected_pixel in zip(actual_pixels, expected_pixels):
        if expected_pixel[3] <= alpha_threshold:
            continue
        total += sum(abs(actual_pixel[index] - expected_pixel[index]) for index in range(3)) / 3
        count += 1

    return total / max(count, 1)


def _image_pixels(image):
    if hasattr(image, "get_flattened_data"):
        return image.get_flattened_data()
    return image.getdata()


if __name__ == "__main__":
    unittest.main()
