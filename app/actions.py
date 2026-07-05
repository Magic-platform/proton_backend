import email
import os
import ssl
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid, parseaddr, parsedate_to_datetime

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
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=os.getenv("MAIL_MESSAGE_ID_DOMAIN", "proton.api.abrakdabra.io"))

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


def get_header(message, name: str):
    try:
        value = message.get(name)
        return str(value) if value is not None else None
    except Exception:
        for header_name, raw_value in message.raw_items():
            if header_name.lower() == name.lower():
                return raw_value

    return None


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


def update_email_flags(
    uid: int,
    mailbox: str = "INBOX",
    seen: bool | None = None,
    flagged: bool | None = None,
):
    if seen is None and flagged is None:
        raise ValueError("At least one flag must be provided")

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

        client.select_folder(mailbox, readonly=False)

        existing = client.fetch([uid], ["FLAGS"])

        if uid not in existing:
            raise LookupError("email not found")

        if seen is not None:
            if seen:
                client.add_flags([uid], [b"\\Seen"])
            else:
                client.remove_flags([uid], [b"\\Seen"])

        if flagged is not None:
            if flagged:
                client.add_flags([uid], [b"\\Flagged"])
            else:
                client.remove_flags([uid], [b"\\Flagged"])

        updated = client.fetch([uid], ["FLAGS"])

        if uid not in updated:
            raise LookupError("email not found")

        flags = updated[uid].get(b"FLAGS", ())

        return {
            "uid": str(uid),
            "mailbox": mailbox,
            "seen": b"\\Seen" in flags,
            "flagged": b"\\Flagged" in flags,
        }


def get_inbox(
    limit: int = 100,
    mailbox: str = "INBOX",
    unread_only: bool = False,
    before_uid: int | None = None,
    include_body: bool = True,
    body_after_uid: int | None = None,
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

        partial_body_fetch = include_body and body_after_uid is not None

        if partial_body_fetch:
            raw_messages = client.fetch(selected_uids, ["BODY.PEEK[HEADER]", "FLAGS"])
            body_uids = [uid for uid in selected_uids if uid > body_after_uid]
            body_messages = client.fetch(body_uids, ["BODY.PEEK[]"]) if body_uids else {}
        else:
            fetch_parts = ["BODY.PEEK[]", "FLAGS"] if include_body else ["BODY.PEEK[HEADER]", "FLAGS"]
            raw_messages = client.fetch(selected_uids, fetch_parts)
            body_messages = {}

        messages = []

        for uid in reversed(selected_uids):
            data = raw_messages[uid]
            if partial_body_fetch:
                raw_email = data[b"BODY[HEADER]"]
                raw_body_email = body_messages.get(uid, {}).get(b"BODY[]")
            else:
                raw_email = data[b"BODY[]"] if include_body else data[b"BODY[HEADER]"]
                raw_body_email = raw_email if include_body else None

            flags = data.get(b"FLAGS", ())
            parsed = email.message_from_bytes(raw_email, policy=policy.default)
            parsed_body = (
                email.message_from_bytes(raw_body_email, policy=policy.default)
                if raw_body_email
                else None
            )
            body_text = extract_text_body(parsed_body) if parsed_body else None
            body_html = extract_html_body(parsed_body) if parsed_body else None

            messages.append({
                "uid": str(uid),
                "message_id": get_header(parsed, "Message-ID"),
                "from": parse_one_address(get_header(parsed, "From")),
                "to": parse_many_addresses(get_header(parsed, "To")),
                "cc": parse_many_addresses(get_header(parsed, "Cc")),
                "subject": get_header(parsed, "Subject"),
                "date": parse_email_date(get_header(parsed, "Date")),
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
