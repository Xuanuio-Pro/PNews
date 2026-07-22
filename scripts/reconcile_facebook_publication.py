import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.settings import DATABASE_PATH  # noqa: E402
from services.facebook_models import FacebookPublicationRepository, now_iso  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="Reconcile publication sau khi đã kiểm tra kết quả trực tiếp trên Facebook."
    )
    parser.add_argument("--publication-id", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--facebook-post-id", help="Post đã tồn tại; đánh dấu publication PUBLISHED.")
    action.add_argument(
        "--safe-to-retry",
        action="store_true",
        help="Đã xác minh post chưa được tạo; chuyển publication về FAILED để retry.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    repository = FacebookPublicationRepository(DATABASE_PATH)
    publication = repository.get_by_id(args.publication_id)
    if not publication:
        print("Không tìm thấy publication.", file=sys.stderr)
        return 2
    if args.facebook_post_id:
        repository.update_publication(
            publication.id,
            status="PUBLISHED",
            facebook_post_id=args.facebook_post_id.strip(),
            published_at=now_iso(),
            last_error="",
        )
        print(f"Đã reconcile {publication.id} -> PUBLISHED ({args.facebook_post_id.strip()}).")
        return 0
    repository.update_publication(
        publication.id,
        status="FAILED",
        last_error="Operator đã xác minh Facebook chưa tạo post; an toàn để retry.",
    )
    print(f"Đã reconcile {publication.id} -> FAILED; có thể retry cùng batch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
