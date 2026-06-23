import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent
APP_DIR = ROOT_DIR / "app"
sys.path.insert(0, str(APP_DIR))

from actions import send_email  # noqa: E402
from scheduled_store import (  # noqa: E402
    claim_due_mail,
    init_db,
    mark_failed_or_retry,
    mark_sent,
    reset_stale_processing,
)


MAX_JOBS_PER_RUN = 50


async def process_one(mail: dict) -> None:
    try:
        await send_email(
            to=mail["to"],
            subject=mail["subject"],
            text=mail["text"],
            html=mail.get("html"),
            cc=mail.get("cc") or [],
            bcc=mail.get("bcc") or [],
        )
    except Exception as exc:
        updated = mark_failed_or_retry(mail["id"], f"{type(exc).__name__}: {exc}")
        status = updated["status"] if updated else "missing"
        print(f"scheduled_mail_failed id={mail['id']} status={status} error={type(exc).__name__}: {exc}")
        return

    mark_sent(mail["id"])
    print(f"scheduled_mail_sent id={mail['id']}")


async def main() -> None:
    load_dotenv(ROOT_DIR / ".env")
    init_db()
    stale_count = reset_stale_processing()

    if stale_count:
        print(f"scheduled_mail_stale_reset count={stale_count}")

    processed = 0

    while processed < MAX_JOBS_PER_RUN:
        mail = claim_due_mail()

        if mail is None:
            break

        await process_one(mail)
        processed += 1

    print(f"scheduled_mail_worker_done processed={processed}")


if __name__ == "__main__":
    asyncio.run(main())
