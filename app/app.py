from fastapi import FastAPI,Header,HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from actions import send_email,get_inbox
from dotenv import load_dotenv
import os

load_dotenv()
app = FastAPI()
API_TOKEN = os.environ["API_TOKEN"]


class SendEmailRequest(BaseModel):
    to: list[EmailStr] = Field(..., min_length=1)
    subject: str = Field(..., min_length=1, max_length=255)
    text: str = Field(..., min_length=1)
    html: str | None = None
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)


class SendEmailResponse(BaseModel):
    ok: bool


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

@app.get("/inbox",response_model=InboxResponse)
def get_inbox_route(
    limit : int = 100,
    mailbox : str = "INBOX",
    unread_only : bool = False,
    before_uid : int | None = None,
    include_body : bool = True,
    authorization : str | None = Header(default=None)
):
    
    check_auth(authorization)

    messages = get_inbox(
        limit,
        mailbox=mailbox,
        unread_only=unread_only, 
        before_uid=before_uid,
        include_body=include_body,
    )

    return InboxResponse(**messages)
