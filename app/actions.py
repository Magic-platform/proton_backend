import email
import os
import ssl
from email import policy
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

import aiosmtplib
from dotenv import load_dotenv
from imapclient import IMAPClient

load_dotenv()

context = ssl.create_default_context()
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE


async def send_email(
    to: list[str],
    subject: str,
    text: str,
    html: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
):
    cc = cc or []
    bcc = bcc or []
    recipients = to + cc + bcc

    if not recipients:
        raise ValueError("At least one recipient is required")

    msg = EmailMessage()
    msg["From"] = os.environ["BRIDGE_USER"]
    msg["To"] = ", ".join(to)

    if cc:
        msg["Cc"] = ", ".join(cc)

    msg["Subject"] = subject
    msg.set_content(text)

    if html:
        msg.add_alternative(html, subtype="html")

    await aiosmtplib.send(
        msg,
        recipients=recipients,
        hostname=os.getenv("BRIDGE_HOST", "127.0.0.1"),
        port=int(os.getenv("BRIDGE_SMTP_PORT", "1025")),
        username=os.environ["BRIDGE_USER"],
        password=os.environ["BRIDGE_PASSWORD"],
        start_tls=True,
        tls_context=context,
        timeout=20,
    )


def parse_one_address(value: str | None):
    name, address = parseaddr(value or "")
    return {
        "name": name or None,
        "email": address or None,
    }


def parse_many_addresses(value: str | None):
    addresses = getaddresses([value or ""])
    return [
        {
            "name": name or None,
            "email": address,
        }
        for name, address in addresses
        if address
    ]


def parse_email_date(value: str | None):
    if not value:
        return None

    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, IndexError, AttributeError):
        return value


def extract_text_body(message):
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue

            if part.get_content_type() == "text/plain":
                return part.get_content()

        return None

    if message.get_content_type() == "text/plain":
        return message.get_content()

    return None


def extract_html_body(message):
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue

            if part.get_content_type() == "text/html":
                return part.get_content()

        return None

    if message.get_content_type() == "text/html":
        return message.get_content()

    return None


def make_snippet(text: str | None, max_length: int = 240):
    if not text:
        return None

    cleaned = " ".join(text.split())

    if len(cleaned) <= max_length:
        return cleaned

    return cleaned[:max_length] + "..."


def get_inbox(
    limit: int = 100,
    mailbox: str = "INBOX",
    unread_only: bool = False,
    before_uid: int | None = None,
    include_body: bool = True,
):
    max_limit = 200 if include_body else 1000
    limit = max(1, min(limit, max_limit))
    criteria = ["UNSEEN"] if unread_only else ["ALL"]

    with IMAPClient(
        host=os.getenv("BRIDGE_HOST", "127.0.0.1"),
        port=int(os.getenv("BRIDGE_IMAP_PORT", "1143")),
        ssl=False,
        timeout=20,
    ) as client:
        client.starttls(context)
        client.login(
            os.environ["BRIDGE_USER"],
            os.environ["BRIDGE_PASSWORD"],
        )

        client.select_folder(mailbox, readonly=True)

        uids = client.search(criteria)

        if before_uid is not None:
            uids = [uid for uid in uids if uid < before_uid]

        total_matching = len(uids)
        selected_uids = uids[-limit:]

        if not selected_uids:
            return {
                "messages": [],
                "count": 0,
                "has_more": False,
                "next_before_uid": None,
            }

        fetch_parts = ["BODY.PEEK[]", "FLAGS"] if include_body else ["BODY.PEEK[HEADER]", "FLAGS"]
        raw_messages = client.fetch(selected_uids, fetch_parts)
        messages = []

        for uid in reversed(selected_uids):
            data = raw_messages[uid]
            raw_email = data[b"BODY[]"] if include_body else data[b"BODY[HEADER]"]
            flags = data.get(b"FLAGS", ())
            parsed = email.message_from_bytes(raw_email, policy=policy.default)
            body_text = extract_text_body(parsed) if include_body else None
            body_html = extract_html_body(parsed) if include_body else None

            messages.append({
                "uid": str(uid),
                "message_id": parsed.get("Message-ID"),
                "from": parse_one_address(parsed.get("From")),
                "to": parse_many_addresses(parsed.get("To")),
                "cc": parse_many_addresses(parsed.get("Cc")),
                "subject": parsed.get("Subject"),
                "date": parse_email_date(parsed.get("Date")),
                "seen": b"\\Seen" in flags,
                "answered": b"\\Answered" in flags,
                "flagged": b"\\Flagged" in flags,
                "snippet": make_snippet(body_text),
                "body_text": body_text,
                "body_html": body_html,
            })

        has_more = total_matching > len(selected_uids)
        next_before_uid = str(min(selected_uids)) if has_more else None

        return {
            "messages": messages,
            "count": len(messages),
            "has_more": has_more,
            "next_before_uid": next_before_uid,
        }
