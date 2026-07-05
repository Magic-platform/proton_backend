from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from actions import send_email,get_inbox,update_email_flags
from dotenv import load_dotenv
import os
from scheduled_store import (
    cancel_scheduled_mail,
    create_scheduled_mail,
    get_scheduled_mail,
    init_db,
    list_scheduled_mails,
    parse_utc_iso,
    to_utc_iso,
)

load_dotenv()
app = FastAPI()
API_TOKEN = os.environ["API_TOKEN"]
init_db()


class SendEmailRequest(BaseModel):
    to: list[EmailStr] = Field(..., min_length=1)
    subject: str = Field(..., min_length=1, max_length=255)
    text: str = Field(..., min_length=1)
    html: str | None = None
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)


class SendEmailResponse(BaseModel):
    ok: bool


class ScheduledMailCreateRequest(BaseModel):
    to: list[EmailStr] = Field(..., min_length=1)
    subject: str = Field(..., min_length=1, max_length=255)
    text: str = Field(..., min_length=1)
    scheduled_at: str
    html: str | None = None
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)
    base44_email_id: str | None = None

    @field_validator("scheduled_at")
    @classmethod
    def validate_scheduled_at(cls, value: str) -> str:
        try:
            return to_utc_iso(parse_utc_iso(value))
        except ValueError as exc:
            raise ValueError("scheduled_at must be an ISO 8601 datetime with timezone") from exc


class ScheduledMailResponse(BaseModel):
    id: str
    idempotency_key: str
    base44_email_id: str | None = None
    to: list[str]
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str
    text: str
    html: str | None = None
    scheduled_at: str
    status: str
    attempts: int
    max_attempts: int
    locked_at: str | None = None
    last_attempt_at: str | None = None
    sent_at: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class ScheduledMailCreateResponse(BaseModel):
    id: str
    status: str
    scheduled_at: str


class ScheduledMailListResponse(BaseModel):
    items: list[ScheduledMailResponse]
    count: int


class ScheduledMailStatusResponse(BaseModel):
    id: str
    status: str


class EmailAddress(BaseModel):
    name: str | None = None
    email: str | None = None


class InboxMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uid: str
    message_id: str | None = None
    from_: EmailAddress = Field(alias="from")
    to: list[EmailAddress] = Field(default_factory=list)
    cc: list[EmailAddress] = Field(default_factory=list)
    subject: str | None = None
    date: str | None = None
    seen: bool
    answered: bool
    flagged: bool
    snippet: str | None = None
    body_text: str | None = None
    body_html: str | None = None


class InboxResponse(BaseModel):
    messages: list[InboxMessage]
    count: int
    has_more: bool
    next_before_uid: str | None = None


class EmailFlagsUpdateRequest(BaseModel):
    seen: bool | None = None
    flagged: bool | None = None


class EmailFlagsResponse(BaseModel):
    uid: str
    mailbox: str
    seen: bool
    flagged: bool


def check_auth(authorization : str | None):
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401,detail="unauthorized")


@app.post("/send",response_model=SendEmailResponse)
async def send(request : SendEmailRequest,authorization : str | None = Header(default=None)):

    check_auth(authorization=authorization)

    await send_email(
        to=request.to,
        subject=request.subject,
        text=request.text,
        html=request.html,
        cc=request.cc,
        bcc=request.bcc,
    )
    return SendEmailResponse(ok=True)


@app.post("/scheduled-mails", response_model=ScheduledMailCreateResponse)
def create_scheduled_mail_route(
    request: ScheduledMailCreateRequest,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    check_auth(authorization=authorization)

    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")

    mail = create_scheduled_mail(
        idempotency_key=idempotency_key,
        to=[str(item) for item in request.to],
        cc=[str(item) for item in request.cc],
        bcc=[str(item) for item in request.bcc],
        subject=request.subject,
        text=request.text,
        html=request.html,
        scheduled_at=request.scheduled_at,
        base44_email_id=request.base44_email_id,
    )

    return ScheduledMailCreateResponse(
        id=mail["id"],
        status=mail["status"],
        scheduled_at=mail["scheduled_at"],
    )


@app.get("/scheduled-mails", response_model=ScheduledMailListResponse)
def list_scheduled_mails_route(
    status: str | None = None,
    limit: int = 50,
    before_created_at: str | None = None,
    authorization: str | None = Header(default=None),
):
    check_auth(authorization=authorization)

    try:
        result = list_scheduled_mails(
            status=status,
            limit=limit,
            before_created_at=before_created_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ScheduledMailListResponse(**result)


@app.get("/scheduled-mails/{mail_id}", response_model=ScheduledMailResponse)
def get_scheduled_mail_route(
    mail_id: str,
    authorization: str | None = Header(default=None),
):
    check_auth(authorization=authorization)
    mail = get_scheduled_mail(mail_id)

    if mail is None:
        raise HTTPException(status_code=404, detail="scheduled mail not found")

    return ScheduledMailResponse(**mail)


@app.post("/scheduled-mails/{mail_id}/cancel", response_model=ScheduledMailStatusResponse)
def cancel_scheduled_mail_route(
    mail_id: str,
    authorization: str | None = Header(default=None),
):
    check_auth(authorization=authorization)
    mail = cancel_scheduled_mail(mail_id)

    if mail is None:
        raise HTTPException(status_code=404, detail="scheduled mail not found")

    return ScheduledMailStatusResponse(id=mail["id"], status=mail["status"])


@app.patch("/emails/{uid}/flags", response_model=EmailFlagsResponse)
def update_email_flags_route(
    uid: int,
    request: EmailFlagsUpdateRequest,
    mailbox: str = "INBOX",
    authorization: str | None = Header(default=None),
):
    check_auth(authorization)

    if request.seen is None and request.flagged is None:
        raise HTTPException(status_code=400, detail="At least one flag must be provided")

    try:
        result = update_email_flags(
            uid,
            mailbox=mailbox,
            seen=request.seen,
            flagged=request.flagged,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="email not found") from exc

    return EmailFlagsResponse(**result)


@app.get("/inbox",response_model=InboxResponse)
def get_inbox_route(
    limit : int = 100,
    mailbox : str = "INBOX",
    unread_only : bool = False,
    before_uid : int | None = None,
    include_body : bool = True,
    body_after_uid : int | None = None,
    authorization : str | None = Header(default=None)
):
    
    check_auth(authorization)

    messages = get_inbox(
        limit,
        mailbox=mailbox,
        unread_only=unread_only, 
        before_uid=before_uid,
        include_body=include_body,
        body_after_uid=body_after_uid,
    )

    return InboxResponse(**messages)
