from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from actions import send_email,get_inbox


app = FastAPI()


class SendEmailRequest(BaseModel):
    to: list[EmailStr] = Field(..., min_length=1)
    subject: str = Field(..., min_length=1, max_length=255)
    text: str = Field(..., min_length=1)
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)


class SendEmailResponse(BaseModel):
    ok: bool


class EmailAddress(BaseModel):
    name: str | None = None
    email: EmailStr | None = None


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


class InboxResponse(BaseModel):
    messages: list[InboxMessage]
    count: int

@app.post("/send",response_model=SendEmailResponse)
async def send(request : SendEmailRequest):
    await send_email(
        request.to,
        request.subject,
        request.text,
        request.cc,
        request.bcc
    )
    return SendEmailResponse(ok=True)

@app.get("/inbox",response_model=InboxResponse)
def get_inbox_route(
    limit : int = 20,
    mailbox : str = "INBOX",
    unread_only : bool = False
):
    messages = get_inbox(
        limit,
        mailbox=mailbox,
        unread_only=unread_only, 
    )

    return InboxResponse(
        messages=messages,
        count=len(messages)
    )

