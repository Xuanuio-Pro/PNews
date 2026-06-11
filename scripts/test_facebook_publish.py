import json
import os
import sys
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.facebook_service import (  # noqa: E402
    FacebookPublishError,
    getPostInfo,
    mask_token,
    publishTextPost,
)


TEST_MESSAGE = f"""TEST ĐĂNG BÀI TỪ PNEWS
Cập nhật ngày {datetime.now().strftime('%d/%m/%Y %H:%M')}

Đây là bài kiểm tra kết nối Facebook Graph API từ hệ thống PNews.

Nguồn: PNews
🔗 Xem chi tiết: https://p-tech.xyz

#PNews #PTIT #TinTucCongNghe"""


def load_local_env(path=BASE_DIR / ".env"):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main():
    load_local_env()
    page_id = os.environ.get("FACEBOOK_PAGE_ID", "")
    token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "")
    version = os.environ.get("FACEBOOK_GRAPH_API_VERSION", "v25.0")

    print(f"FACEBOOK_PAGE_ID={page_id or '(missing)'}")
    print(f"FACEBOOK_GRAPH_API_VERSION={version}")
    print(f"FACEBOOK_PAGE_ACCESS_TOKEN={mask_token(token) or '(missing)'}")

    try:
        response = publishTextPost(TEST_MESSAGE)
        print("Publish response:")
        print(json.dumps(response, ensure_ascii=False, indent=2))

        post_id = response.get("id")
        if post_id:
            post_info = getPostInfo(post_id)
            print("Post info:")
            print(json.dumps(post_info, ensure_ascii=False, indent=2))
    except FacebookPublishError as exc:
        print(f"Facebook publish test failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected test error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
