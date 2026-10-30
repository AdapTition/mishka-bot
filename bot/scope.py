"""Working out who a document is written for and whether it replaces an older one."""

import logging
import re
from difflib import SequenceMatcher

from .forest import (
    MAP_TEXT,
    MITTEN_BY_NAME,
    PART_NAMES,
    Audience,
    find_mittens,
    find_parts,
    is_forest_wide,
)
from .llm import LLM, LLMUnavailable
from .storage import Document

log = logging.getLogger(__name__)

INTRO_CHARS = 350


def classify_rules(title: str, text: str) -> Audience | None:
    """Explicit cues: the document title first, then its intro. None if unclear."""
    if mittens := find_mittens(title):
        return Audience(mittens=mittens)
    if parts := find_parts(title):
        return Audience(parts=parts)
    if is_forest_wide(title):
        return Audience(forest=True)

    intro = text[:INTRO_CHARS]
    if is_forest_wide(intro):
        return Audience(forest=True)
    if mittens := find_mittens(intro):
        return Audience(mittens=mittens)
    if parts := find_parts(intro):
        return Audience(parts=parts)
    return None


SCOPE_SYSTEM = f"""Ти визначаєш, для кого написано документ-пораду в лісі з восьми рукавичок.
Карта лісу (рукавичка: частина лісу):
{MAP_TEXT}

Порада буває для всього лісу, для однієї чи кількох частин лісу (conifer — хвойний ліс,
deciduous — листяний ліс, river — біля річки) або для конкретних рукавичок.
Визначай ТІЛЬКИ за явними словами документа про те, кому він адресований чи де живуть ті, кому він
призначений: «для мешканців хвойного лісу», «під ялинами» (це хвойний ліс, а не рукавичка «Під ялиною»),
«мешканці рукавички «Під дубом»», «для всіх мешканців лісу».
Якщо документ лише згадує місця (де щось росте, куди йти), але не каже, для кого він, або ти не впевнений —
відповідай unknown. Краще unknown, ніж здогадка.

Відповідь — JSON: {{"audience": "forest" | "parts" | "mittens" | "unknown",
"parts": ["conifer" | "deciduous" | "river"], "mittens": ["<точна назва рукавички>"], "reason": "коротко"}}"""


async def classify_llm(title: str, text: str, llm: LLM) -> Audience | None:
    user = f"Назва файлу: {title}\n\nТекст документа:\n{text[:3000]}"
    try:
        data = await llm.json(SCOPE_SYSTEM, user, max_tokens=1500)
    except LLMUnavailable:
        return None
    log.info("LLM classification '%s': %s", title, data)
    kind = data.get("audience")
    if kind == "forest":
        return Audience(forest=True)
    if kind == "parts":
        parts = [p for p in data.get("parts", []) if p in PART_NAMES]
        return Audience(parts=parts) if parts else None
    if kind == "mittens":
        mittens = [m for m in data.get("mittens", []) if m in MITTEN_BY_NAME]
        return Audience(mittens=mittens) if mittens else None
    return None


def normalize_title(title: str) -> str:
    title = title.lower().replace("«", "").replace("»", "").replace('"', "")
    title = re.sub(r"\b(оновлен\w*|нов\w*|версія|редакція|v\d+)\b", " ", title)
    title = re.sub(r"[\d_\-().,]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


REPLACE_SYSTEM = """Ти допомагаєш вести архів документів-порад лісу. Звір надіслав новий документ.
Визнач, чи це новіша версія одного з наявних документів для того самого місця: та сама тема й той самий вид
документа (наприклад, оновлені членські внески замість старих внесків). Різні теми — це не заміна.
Відповідь — JSON: {"replaces": <номер документа або null>}"""


async def find_replaced(title: str, text: str, audience: Audience, docs: list[Document], llm: LLM) -> Document | None:
    """Finds the active document for the same place that the new document should replace."""
    same_place = [d for d in docs if d.audience.key() == audience.key()]
    if not same_place:
        return None
    norm = normalize_title(title)
    best = max(same_place, key=lambda d: SequenceMatcher(None, norm, normalize_title(d.title)).ratio())
    if SequenceMatcher(None, norm, normalize_title(best.title)).ratio() >= 0.85:
        return best

    listing = "\n".join(f"[{d.id}] «{d.title}»: {d.text[:200]}" for d in same_place)
    user = f"Новий документ «{title}»:\n{text[:1500]}\n\nНаявні документи для того самого місця:\n{listing}"
    try:
        data = await llm.json(REPLACE_SYSTEM, user, max_tokens=1000)
    except LLMUnavailable:
        return None
    by_id = {d.id: d for d in same_place}
    try:
        return by_id.get(int(data.get("replaces")))
    except (TypeError, ValueError):
        return None
