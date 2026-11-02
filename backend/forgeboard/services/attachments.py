"""Attachment storage on a persistent volume.

Security measures:
* Files are stored under random server-generated keys (no user-controlled paths).
* Size is enforced while streaming (never buffered fully in memory).
* Content type is determined from magic bytes and must be on an allow-list;
  active content (HTML, SVG, JS, executables) is rejected.
* Downloads always use `Content-Disposition: attachment`, `nosniff`, and a
  sandbox CSP (see the router).
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time
import unicodedata
import uuid
from pathlib import Path

import anyio
import puremagic
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forgeboard.authz import Need, load_task_access
from forgeboard.config import get_settings
from forgeboard.errors import Forbidden, NotFound, PayloadTooLarge, UnsupportedMediaType, ValidationFailed
from forgeboard.logging import get_logger
from forgeboard.models import Attachment, Task, User
from forgeboard.services import activity

log = get_logger(__name__)

# Allowed types detected by magic bytes -> canonical MIME type
ALLOWED_BINARY = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
# Plain-text formats (no magic bytes) accepted only if the content is valid UTF-8
# without markup that a browser could sniff as HTML.
ALLOWED_TEXT = {
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".log": "text/plain",
    ".json": "application/json",
}
CHUNK = 64 * 1024


def storage_root() -> Path:
    return Path(get_settings().attachments_dir)


def _path_for(key: str) -> Path:
    # keys are hex only; shard by prefix to keep directories small
    return storage_root() / key[:2] / key


def sanitize_filename(name: str | None) -> str:
    name = unicodedata.normalize("NFC", (name or "file")).replace("\\", "/").split("/")[-1]
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"|?*\x00').strip(" .")
    return (name or "file")[:200]


def _detect(head: bytes, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in ALLOWED_TEXT:
        try:
            text = head.decode("utf-8")
        except UnicodeDecodeError:
            # head may cut a multi-byte char; retry trimmed
            try:
                text = head[:-4].decode("utf-8")
            except UnicodeDecodeError:
                raise UnsupportedMediaType("File is not valid UTF-8 text") from None
        lowered = text.lower()
        if "<script" in lowered or "<html" in lowered or "<svg" in lowered or "\x00" in text:
            raise UnsupportedMediaType("Text file contains active content")
        return ALLOWED_TEXT[ext]
    try:
        matches = puremagic.magic_string(head)
    except puremagic.PureError:
        matches = []
    detected_exts = {m.extension.lower() for m in matches if m.extension}
    if ext in (".zip", ".docx", ".xlsx", ".pptx") and head.startswith(b"PK\x03\x04"):
        return ALLOWED_BINARY[ext]
    if ext == ".jpeg":
        ext = ".jpg"
    if ext in ALLOWED_BINARY and (ext in detected_exts or (ext == ".jpg" and ".jpeg" in detected_exts)):
        return ALLOWED_BINARY[ext]
    raise UnsupportedMediaType(
        "Unsupported or mismatched file type. Allowed: images (png, jpg, gif, webp), pdf, zip, "
        "docx, xlsx, pptx, txt, csv, md, log, json"
    )


async def store_upload(session: AsyncSession, user: User, task_id: uuid.UUID, upload: UploadFile) -> Attachment:
    _, access = await load_task_access(session, user.id, task_id, Need.WRITE)
    s = get_settings()
    filename = sanitize_filename(upload.filename)
    key = secrets.token_hex(20)
    path = _path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    digest = hashlib.sha256()
    size = 0
    head = b""
    try:
        async with await anyio.open_file(tmp, "wb") as fh:
            while chunk := await upload.read(CHUNK):
                size += len(chunk)
                if size > s.max_upload_bytes:
                    raise PayloadTooLarge(f"File exceeds the {s.max_upload_mb} MB limit")
                if len(head) < 8192:
                    head += chunk[: 8192 - len(head)]
                digest.update(chunk)
                await fh.write(chunk)
        if size == 0:
            raise ValidationFailed("File is empty")
        content_type = _detect(head, filename)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    att = Attachment(
        task_id=task_id,
        project_id=access.project.id,
        uploaded_by=user.id,
        filename=filename,
        content_type=content_type,
        size_bytes=size,
        sha256=digest.hexdigest(),
        storage_key=key,
    )
    session.add(att)
    try:
        await session.flush()
        task_title = await session.scalar(select(Task.title).where(Task.id == task_id))
        activity.record(
            session,
            org_id=access.project.org_id,
            project_id=access.project.id,
            task_id=task_id,
            actor_id=user.id,
            type="attachment.added",
            payload={"attachment_id": str(att.id), "filename": filename, "size": size, "task_title": task_title},
        )
        await activity.commit(session)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return att


async def get_for_download(session: AsyncSession, user: User, attachment_id: uuid.UUID) -> tuple[Attachment, Path]:
    att = await session.get(Attachment, attachment_id)
    if att is None:
        raise NotFound("Attachment not found")
    try:
        await load_task_access(session, user.id, att.task_id, Need.READ)
    except NotFound:
        raise NotFound("Attachment not found") from None
    path = _path_for(att.storage_key)
    if not path.is_file():
        log.error("attachment_file_missing", attachment_id=str(att.id))
        raise NotFound("Attachment file is missing")
    return att, path


async def delete_attachment(session: AsyncSession, user: User, attachment_id: uuid.UUID) -> None:
    att = await session.get(Attachment, attachment_id)
    if att is None:
        raise NotFound("Attachment not found")
    try:
        _, access = await load_task_access(session, user.id, att.task_id, Need.WRITE)
    except NotFound:
        raise NotFound("Attachment not found") from None
    if att.uploaded_by != user.id and not access.can_admin:
        raise Forbidden("Only the uploader or an admin can delete this attachment")
    await session.delete(att)
    activity.record(
        session,
        org_id=access.project.org_id,
        project_id=access.project.id,
        task_id=att.task_id,
        actor_id=user.id,
        type="attachment.deleted",
        payload={"attachment_id": str(att.id), "filename": att.filename},
    )
    delete_files_later(session, [att.storage_key])
    await activity.commit(session)


def delete_files_later(session: AsyncSession, keys: list[str]) -> None:
    if not keys:
        return

    def _rm() -> None:
        for k in keys:
            try:
                _path_for(k).unlink(missing_ok=True)
            except OSError:
                log.warning("attachment_unlink_failed", key=k)

    activity.after_commit(session, _rm)


async def sweep_orphans(session: AsyncSession) -> int:
    """Remove files with no DB row (e.g. crash between commit and unlink). Runs at startup."""
    root = storage_root()
    if not root.exists():
        return 0
    known = set((await session.scalars(select(Attachment.storage_key))).all())
    removed = 0
    for shard in root.iterdir():
        if not shard.is_dir():
            continue
        for f in shard.iterdir():
            key = f.name.removesuffix(".part")
            try:
                age = time.time() - f.stat().st_mtime
            except OSError:
                continue
            # Grace period: an upload may have written its file but not yet committed its row.
            if age > 3600 and (key not in known or f.name.endswith(".part")):
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed
