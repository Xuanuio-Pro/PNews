import argparse
import sys

from services.notification_service import NotificationService
from services.notifiers.telegram_notifier import TelegramNotifier


def print_batch_result(result):
    print(
        "Telegram: "
        f"sent={result['sent']}, skipped={result['skipped']}, failed={result['failed']}"
    )
    for message in result.get("messages", [])[:10]:
        print(f"- {message}")


def main():
    parser = argparse.ArgumentParser(description="Send PNews articles to Telegram.")
    parser.add_argument("--test", action="store_true", help="Send a short Telegram test message.")
    parser.add_argument("--article-id", type=int, help="Send one approved/published article.")
    parser.add_argument("--limit", type=int, help="Send latest approved/published articles.")
    parser.add_argument("--chat-id", help="Override TELEGRAM_DEFAULT_CHAT_ID.")
    args = parser.parse_args()

    if not any([args.test, args.article_id, args.limit]):
        parser.error("Choose one of --test, --article-id, or --limit.")

    try:
        if args.test:
            notifier = TelegramNotifier(default_chat_id=args.chat_id)
            notifier.send_message("Test PNews Telegram Bot thanh cong.", chat_id=args.chat_id)
            print("Telegram test message sent.")
            return 0

        service = NotificationService()
        if args.article_id:
            result = service.send_selected_articles_to_telegram([args.article_id], target_id=args.chat_id)
        else:
            result = service.send_latest_approved_to_telegram(limit=args.limit, target_id=args.chat_id)
        print_batch_result(result)
        return 1 if result.get("failed") else 0
    except Exception as exc:
        print(f"Telegram error: {str(exc)[:300]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
