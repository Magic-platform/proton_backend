from dotenv import load_dotenv
import os 
import ssl 
from email.message import EmailMessage

import aiosmtplib

load_dotenv()

async def send_email(to : list[str],subject:str,text : str,cc : list[str] | None = None,bcc : list[str] | None = None):
    cc = cc or []
    bcc = bcc or []

    msg = EmailMessage()
    msg["From"] = os.getenv("BRIDGE_USER")
    msg["To"] = ", ".join(to)

    if cc :
        msg["Cc"] = ", ".join(cc)
    if bcc :
        msg["Bcc"] = ", ".join(bcc)
    
    recipients = to + cc + bcc

    await aiosmtplib.send(
        msg,
        recipients=recipients,
        hostname=os.getenv("BRIDGE_HOST","127.0.0.1"),
        port=int(os.getenv("BRIDGE_SMTP_PORT","1025"))
        
    )