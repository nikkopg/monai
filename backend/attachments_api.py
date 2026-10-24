"""
Attachment routes (Phase 39): the upload trust boundary and the locality read.

A file reaches a parser only after the API key, the size cap (the middleware in
main.py before the form is parsed, `UploadFile.size` here), the magic-byte type
and the account check. It is parsed once, in code, at upload (D-04). The PDF
password lives in memory for this request only: it is never stored, logged,
echoed or written into a note, and a too-long one gets a fixed-text 422.
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text

from backend.attachments import (
    ALLOWED_TYPES_TEXT, MAX_UPLOAD_BYTES, NeedsPassword, current_locality, ingest, llm_target, purge_expired,
    sniff, store, summary_for,
)
from backend.auth import require_api_key
from backend.db import get_session_sync
from backend.models import Account
from backend.schemas import AttachmentUploadOut

log = logging.getLogger(__name__)
router = APIRouter()

MAX_PASSWORD_CHARS = 256


def _prepare(thread_id: uuid.UUID, account_id: int):
    """Lazy purge, check the account, get-or-create the thread: (name, currency, LLM target)."""
    with get_session_sync() as db:
        purge_expired(db)
        acct = db.get(Account, account_id)  # explicit, so a bad id is a 422 and never an FK 500
        if acct is None or acct.type != "liquid":
            raise ValueError("Choose an account that can take transactions.")
        db.execute(
            text("INSERT INTO threads (id, title) VALUES (:id, '') ON CONFLICT (id) DO NOTHING"),
            {"id": thread_id},
        )
        db.commit()
        return acct.name, acct.currency or "IDR", llm_target(db)


def _store(thread_id, filename, mime, kind, data, parsed, account_id):
    with get_session_sync() as db:
        a = store(
            db, thread_id=thread_id, filename=filename, mime=mime, kind=kind, data=data, parsed=parsed,
            account_id=account_id,
        )
        db.commit()
        return a.id


@router.post(
    "/threads/{thread_id}/attachments", response_model=AttachmentUploadOut,
    dependencies=[Depends(require_api_key)],
)
async def upload_attachment(
    thread_id: uuid.UUID,
    file: UploadFile = File(...),
    account_id: int = Form(...),
    password: str | None = Form(None),
):
    if file.size is None or file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 10 MB")
    # by hand: a Form(max_length=) 422 would echo the password back (RESEARCH Pitfall 12)
    if password is not None and len(password) > MAX_PASSWORD_CHARS:
        raise HTTPException(422, "The password is too long.")
    data = await file.read()
    typed = sniff(data)
    if typed is None:
        raise HTTPException(415, ALLOWED_TYPES_TEXT)
    kind_hint, mime = typed
    try:
        name, currency, target = await asyncio.to_thread(_prepare, thread_id, account_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    try:
        parsed = await ingest(
            data, kind_hint=kind_hint, account_name=name, account_currency=currency, password=password,
            target=target,
        )
    except NeedsPassword as e:
        return AttachmentUploadOut(
            attachment_id=None, thread_id=thread_id, kind="pdf_text",
            status="wrong_password" if e.wrong else "needs_password", summary=str(e), row_count=0,
        )
    except Exception as e:  # malformed or truncated file: a 4xx, and only the class name is logged
        log.warning("attachment unreadable: %s", type(e).__name__)
        raise HTTPException(422, "The file could not be read.")
    attachment_id = await asyncio.to_thread(
        _store, thread_id, file.filename or "file", mime, parsed.kind, data, parsed, account_id
    )
    return AttachmentUploadOut(
        attachment_id=attachment_id, thread_id=thread_id, kind=parsed.kind, status=parsed.status,
        summary=summary_for(parsed), row_count=len(parsed.rows),
    )


@router.get("/attachments/locality", dependencies=[Depends(require_api_key)])
async def attachments_locality():
    """{local, destination}: where an attached file would be sent (D-14)."""

    def read():
        with get_session_sync() as db:
            return current_locality(db)

    return await asyncio.to_thread(read)
