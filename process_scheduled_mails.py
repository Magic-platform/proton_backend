import asyncio
import os
import sys
from pathlib import Path

import httpx
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


async def notify_scheduled_mail_webhook(payload: dict) -> None:
    webhook_url = os.getenv("SCHEDULED_EMAIL_WEBHOOK_URL")
    webhook_secret = os.getenv("BASE44_WEBHOOK_SECRET")

    if not webhook_url:
        return

    headers = {}

    if webhook_secret:
        headers["X-Webhook-Secret"] = webhook_secret

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(webhook_url, headers=headers, json=payload)
            response.raise_for_status()
    except Exception as exc:
        print(
            "scheduled_mail_webhook_failed "
            f"automation_id={payload.get('automation_id')} "
            f"status={payload.get('status')} "
            f"error={type(exc).__name__}: {exc}"
        )
        return

    print(
        "scheduled_mail_webhook_sent "
        f"automation_id={payload.get('automation_id')} "
        f"status={payload.get('status')}"
    )


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

        if updated and updated["status"] == "failed":
            await notify_scheduled_mail_webhook(
                {
                    "automation_id": updated["id"],
                    "status": "failed",
                    "error": updated.get("error") or f"{type(exc).__name__}: {exc}",
                }
            )

        return

    updated = mark_sent(mail["id"])
    print(f"scheduled_mail_sent id={mail['id']}")

    if updated:
        await notify_scheduled_mail_webhook(
            {
                "automation_id": updated["id"],
                "status": "sent",
                "sent_at": updated.get("sent_at"),
            }
        )


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
