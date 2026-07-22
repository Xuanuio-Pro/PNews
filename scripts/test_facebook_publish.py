import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config.settings import DATABASE_PATH  # noqa: E402
from services.facebook_api_client import FacebookApiClient  # noqa: E402
from services.facebook_models import FacebookPublicationRepository  # noqa: E402
from services.facebook_publisher import publishFacebookNewsBatch  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="Kiểm tra một Facebook multi-photo post gồm đúng hai ảnh."
    )
    parser.add_argument("--image", action="append", default=[], help="Đường dẫn ảnh; truyền đúng hai lần.")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ tạo JSON preview, không gọi Facebook.")
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Xác nhận cho phép đăng bài thật lên Facebook Page.",
    )
    return parser.parse_args()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    if len(args.image) != 2:
        print("Cần truyền đúng hai tham số --image.", file=sys.stderr)
        return 2
    paths = [str(Path(value).resolve()) for value in args.image]
    missing = [path for path in paths if not Path(path).is_file()]
    if missing:
        print("Không tìm thấy ảnh: " + ", ".join(missing), file=sys.stderr)
        return 2
    if not args.dry_run and not args.confirm_live:
        print("Dùng --dry-run hoặc thêm --confirm-live để cho phép đăng thật.", file=sys.stderr)
        return 2

    marker = datetime.now().strftime("%Y%m%d-%H%M%S")
    articles = [
        {
            "id": -101,
            "title": f"TEST_PHOTO_A_{marker}",
            "summary": "Caption riêng kiểm thử cho ảnh A.",
            "source": "PNews Test",
            "url": "https://p-tech.xyz/test-photo-a",
        },
        {
            "id": -102,
            "title": f"TEST_PHOTO_B_{marker}",
            "summary": "Caption riêng kiểm thử cho ảnh B.",
            "source": "PNews Test",
            "url": "https://p-tech.xyz/test-photo-b",
        },
    ]
    client = FacebookApiClient.from_env(dry_run=args.dry_run)
    repository = FacebookPublicationRepository(DATABASE_PATH)
    publication, response = publishFacebookNewsBatch(
        articles,
        paths,
        batch_id=f"two-photo-api-test-{marker}",
        client=client,
        repository=repository,
        main_caption=(
            f"TIN TỨC MỚI TỪ PNEWS\nTEST_MAIN_{marker}\n\n"
            "👉 Bấm vào từng ảnh để xem nội dung chi tiết."
        ),
        partial_policy="abort",
        min_photos=2,
        concurrency=1,
    )
    safe_print(json.dumps(publication.to_dict(), ensure_ascii=False, indent=2))
    safe_print(json.dumps(response, ensure_ascii=False, indent=2))
    if not args.dry_run:
        print("Hãy mở post và từng ảnh để xác nhận TEST_PHOTO_A/B được giữ riêng biệt.")
    return 0


def safe_print(value):
    text = str(value)
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding))


if __name__ == "__main__":
    raise SystemExit(main())
