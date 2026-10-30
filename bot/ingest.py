"""Loading the archive at startup and accepting new documents from animals."""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from .extract import SUPPORTED, extract_text
from .forest import Audience
from .llm import LLM
from .scope import classify_llm, classify_rules, find_replaced
from .storage import Document, Store

log = logging.getLogger(__name__)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def title_from_filename(filename: str) -> str:
    return Path(filename).stem.replace("_", " ").strip()


async def ingest_archive(archive_dir: Path, store: Store, llm: LLM) -> None:
    """Adds "Forest Archive" documents that are not in the database yet (including OCR of scans)."""
    files = sorted(p for p in archive_dir.iterdir() if p.suffix.lower() in SUPPORTED) if archive_dir.exists() else []
    added = 0
    for path in files:
        data = path.read_bytes()
        digest = sha256(data)
        if store.known_sha(digest):
            continue
        text = await asyncio.to_thread(extract_text, data, path.name)
        title = title_from_filename(path.name)
        audience = classify_rules(title, text) or await classify_llm(title, text, llm)
        if audience is None:
            log.warning("Could not tell who '%s' is for; treating it as advice for the whole forest", title)
            audience = Audience(forest=True)
        store.add(title=title, filename=path.name, text=text, audience=audience, source="archive",
                  sha256=digest, status="active")
        added += 1
        log.info("Archive: '%s' - %s (%d chars)", title, audience.describe(), len(text))
    log.info("Archive: added %d, %d active documents in total", added, len(store.active()))


@dataclass
class Upload:
    doc: Document
    needs_scope: bool


async def accept_upload(data: bytes, filename: str, uploader_id: int, uploader_name: str,
                        store: Store, llm: LLM, text: str) -> Upload:
    """Stores a document from an animal. If it is unclear who it is for, leaves it in pending status."""
    title = title_from_filename(filename)
    audience = classify_rules(title, text) or await classify_llm(title, text, llm)
    doc_id = store.add(
        title=title, filename=filename, text=text, audience=audience or Audience(), source="user",
        sha256=sha256(data), status="pending", uploader_id=uploader_id, uploader_name=uploader_name,
    )
    return Upload(store.get(doc_id), needs_scope=audience is None)


async def activate(doc: Document, store: Store, llm: LLM) -> Document | None:
    """Makes the document active; returns the old document it replaced, if any."""
    others = [d for d in store.active() if d.id != doc.id]
    replaced = await find_replaced(doc.title, doc.text, doc.audience, others, llm)
    if replaced:
        store.set_status(replaced.id, "replaced", replaced_by=doc.id)
    store.set_status(doc.id, "active")
    return replaced
