import argparse
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageStat


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.image_generator import create_news_card  # noqa: E402


DEFAULT_OUTPUT = BASE_DIR / "data" / "qa" / "publication_visual" / "latest.jpg"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Tạo một ảnh ấn phẩm mẫu để kiểm tra trực quan sau khi cập nhật code."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"File ảnh đầu ra (mặc định: {DEFAULT_OUTPUT}).",
    )
    return parser.parse_args()


def build_sample_article():
    return {
        "source": "PTIT",
        "title": (
            "Sinh viên PTIT phát triển nền tảng trí tuệ nhân tạo hỗ trợ "
            "tổng hợp và kiểm chứng tin tức số"
        ),
        "url": "https://example.com/pnews-visual-smoke-test",
        "thumbnail": "",
        "summary": (
            "Ấn phẩm mẫu dùng để kiểm tra logo, ảnh nền, kiểu chữ, xuống dòng, "
            "khoảng cách và khả năng hiển thị tiếng Việt sau mỗi lần cập nhật code."
        ),
        "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "content_topic": "Khoa học - Công nghệ",
        "category": "Khoa học - Công nghệ",
    }


def validate_output(output_path):
    with Image.open(output_path) as image:
        image.load()
        width, height = image.size
        extrema = ImageStat.Stat(image.convert("RGB")).extrema

    if (width, height) != (1080, 1350):
        raise RuntimeError(f"Kích thước ảnh không đúng: {width}x{height}; cần 1080x1350.")
    if all(low == high for low, high in extrema):
        raise RuntimeError("Ảnh đầu ra chỉ có một màu, renderer có thể đang bị lỗi.")
    return width, height


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    create_news_card(build_sample_article(), output_path)
    width, height = validate_output(output_path)

    print("[OK] Đã tạo ảnh ấn phẩm kiểm tra trực quan.")
    print(f"[OK] Kích thước: {width}x{height}")
    print(f"[FILE] {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
