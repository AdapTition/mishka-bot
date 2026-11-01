"""Telegram handlers: questions, new documents, place choice, deletion."""

import asyncio
import logging
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction, ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User
from aiogram.utils.chat_action import ChatActionSender

from .config import Config
from .extract import SUPPORTED, UnsupportedFormat, extract_text
from .forest import MITTENS, PART_NAMES, Audience
from .ingest import accept_upload, activate, sha256
from .llm import LLM, LLMUnavailable
from .qa import Answer, respond
from .storage import Document, Store

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

MAX_FILE_BYTES = 20 * 1024 * 1024  # Telegram does not give bots files larger than this
SESSION_TTL = 30 * 60
HISTORY_MESSAGES = 6  # 3 question-answer exchanges: history goes into every understanding request

HELLO = (
    "Привіт! Я Мишка-довідник лісу 🐭\n\n"
    "• Постав мені питання — я знайду відповідь у документах-порадах і скажу, з якого документа її взяла.\n"
    "• Якщо порада залежить від місця, назви рукавичку в питанні, наприклад: «Коли здавати внески під дубом?»\n"
    "• Надішли PDF, Word (.docx) або .txt — і я додам пораду в архів. Нова версія документа для того самого "
    "місця замінить стару.\n\n"
    "Команди:\n/docs — усі документи\n/my — документи, які надіслав ти (тут їх можна видалити)"
)
BUSY = "Ой, я зараз трохи захекалась і не можу подумати 🐭 Спробуй, будь ласка, за хвилинку."


class Sessions:
    """Conversation context: recent turns and the question waiting for a mitten choice."""

    def __init__(self):
        self._history: dict[int, deque[tuple[str, str, float]]] = {}
        self._pending: dict[int, str] = {}

    def history(self, chat_id: int) -> list[tuple[str, str]]:
        now = time.time()
        return [(role, text) for role, text, ts in self._history.get(chat_id, ()) if now - ts < SESSION_TTL]

    def add(self, chat_id: int, role: str, text: str) -> None:
        self._history.setdefault(chat_id, deque(maxlen=HISTORY_MESSAGES)).append((role, text[:400], time.time()))

    def set_pending(self, chat_id: int, question: str) -> None:
        self._pending[chat_id] = question

    def pop_pending(self, chat_id: int) -> str | None:
        return self._pending.pop(chat_id, None)


def display_name(user: User) -> str:
    return f"{user.full_name} (@{user.username})" if user.username else user.full_name


def source_line(doc: Document) -> str:
    line = f"📄 «{doc.title}»"
    return line + f" — надіслав(ла) {doc.uploader_name}" if doc.from_user else line


def render(answer: Answer, header: str = "") -> str:
    text = (header + "\n\n" if header else "") + answer.text
    if answer.sources:
        text += "\n\nДжерела:\n" + "\n".join(source_line(d) for d in answer.sources)
    return text


def mitten_keyboard() -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=m.name, callback_data=f"q:{i}") for i, m in enumerate(MITTENS)]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i:i + 2] for i in range(0, len(buttons), 2)])


def now_local(cfg: Config) -> datetime:
    return datetime.now(ZoneInfo(cfg.timezone))


async def reply_answer(message: Message, text: str, store: Store, llm: LLM, sessions: Sessions, cfg: Config,
                       forced_mitten: str | None = None, header: str = "") -> None:
    chat_id = message.chat.id
    try:
        # The "typing…" indicator lasts while the model thinks (on a rate limit this can take up to half a minute).
        async with ChatActionSender.typing(bot=message.bot, chat_id=chat_id):
            answer = await respond(text, sessions.history(chat_id), store, llm, now_local(cfg), forced_mitten)
    except LLMUnavailable:
        await message.answer(BUSY)
        return
    sessions.add(chat_id, "user", text if not forced_mitten else f"{text} — рукавичка «{forced_mitten}»")
    sessions.add(chat_id, "bot", answer.text)
    if answer.need_place:
        sessions.set_pending(chat_id, answer.question)
        await message.answer(answer.text, reply_markup=mitten_keyboard())
        return
    await message.answer(render(answer, header))


# ---------- commands ----------

@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(HELLO)


@router.message(Command("docs"))
async def cmd_docs(message: Message, store: Store) -> None:
    groups: dict[str, list[str]] = {}
    for doc in store.active():
        groups.setdefault(doc.audience.describe(), []).append(source_line(doc))
    lines = [f"Документів в архіві: {sum(len(v) for v in groups.values())}"]
    for audience in sorted(groups, key=lambda a: (a != "увесь ліс", a)):
        lines.append(f"\n🌲 Для кого: {audience}")
        lines.extend(groups[audience])
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) > 3800:
            await message.answer(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await message.answer(chunk)


@router.message(Command("my"))
async def cmd_my(message: Message, store: Store) -> None:
    docs = store.by_uploader(message.from_user.id)
    if not docs:
        await message.answer("Ти ще не надсилав(ла) мені документів.")
        return
    for doc in docs:
        status = "чекає, поки ти скажеш, для кого він" if doc.status == "pending" else doc.audience.describe()
        await message.answer(
            f"📄 «{doc.title}» — {status}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🗑 Видалити", callback_data=f"del:{doc.id}")
            ]]),
        )


@router.callback_query(F.data.startswith("del:"))
async def on_delete(callback: CallbackQuery, store: Store) -> None:
    doc = store.get(int(callback.data.split(":")[1]))
    if not doc or doc.uploader_id != callback.from_user.id or doc.status not in ("active", "pending"):
        await callback.answer("Видалити можна лише свій документ.", show_alert=True)
        return
    restored = store.delete(doc.id)
    text = f"🗑 Документ «{doc.title}» видалено."
    if restored:
        text += f"\nПовернула попередню версію: «{restored.title}»."
    await callback.message.edit_text(text)
    await callback.answer()


# ---------- new documents ----------

SCOPE_CODES = {"f": None, "c": "conifer", "d": "deciduous", "r": "river"}


def scope_keyboard(doc: Document) -> InlineKeyboardMarkup:
    a = doc.audience

    def button(label: str, code: str, checked: bool) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=("✅ " if checked else "") + label, callback_data=f"sc:{doc.id}:{code}")

    rows = [[button("Увесь ліс", "f", a.forest)]]
    rows.append([button(PART_NAMES[p].capitalize(), c, p in a.parts) for c, p in SCOPE_CODES.items() if p])
    mittens = [button(m.name, f"m{i}", m.name in a.mittens) for i, m in enumerate(MITTENS)]
    rows += [mittens[i:i + 2] for i in range(0, len(mittens), 2)]
    rows.append([InlineKeyboardButton(text="Готово ➡️", callback_data=f"sc:{doc.id}:ok")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def toggle(audience: Audience, code: str) -> Audience:
    if code == "f":
        return Audience(forest=not audience.forest)
    parts, mittens = list(audience.parts), list(audience.mittens)
    if code in SCOPE_CODES:
        part = SCOPE_CODES[code]
        parts.remove(part) if part in parts else parts.append(part)
    else:
        name = MITTENS[int(code[1:])].name
        mittens.remove(name) if name in mittens else mittens.append(name)
    return Audience(parts=parts, mittens=mittens)


async def activation_message(doc: Document, store: Store, llm: LLM) -> str:
    replaced = await activate(doc, store, llm)
    text = f"Дякую! Додала «{doc.title}» до архіву. Для кого: {doc.audience.describe()}."
    if replaced:
        text += f"\nЦе новіша версія документа «{replaced.title}» — стару я прибрала, тепер звірі бачать тільки нову."
    return text


@router.message(F.document)
async def on_document(message: Message, bot: Bot, store: Store, llm: LLM) -> None:
    document = message.document
    filename = document.file_name or "документ"
    if not filename.lower().endswith(SUPPORTED):
        await message.answer("Я читаю тільки PDF, Word (.docx) і текстові файли (.txt). "
                             "Якщо це старий .doc — збережи його як .docx, будь ласка.")
        return
    if (document.file_size or 0) > MAX_FILE_BYTES:
        await message.answer("Файл завеликий — Telegram дає мені файли до 20 МБ.")
        return

    await message.answer(f"Читаю «{filename}»… 🐭")
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    data = (await bot.download(document)).read()

    if existing := store.find_by_sha(sha256(data), ("active", "pending")):
        await message.answer(f"Такий документ у мене вже є: «{existing.title}».")
        return
    try:
        text = await asyncio.to_thread(extract_text, data, filename)
    except UnsupportedFormat:
        await message.answer("Не вмію читати такий формат.")
        return
    except Exception:
        log.exception("Could not read %s", filename)
        await message.answer("Не змогла відкрити цей файл — можливо, він пошкоджений.")
        return
    if len(text) < 20:
        await message.answer("Не знайшла в документі тексту, тож додати його не можу.")
        return

    upload = await accept_upload(data, filename, message.from_user.id, display_name(message.from_user),
                                 store, llm, text)
    if upload.needs_scope:
        await message.answer(
            f"З документа «{upload.doc.title}» мені незрозуміло, для кого ця порада, а вгадувати не хочу. "
            "Познач, будь ласка, для кого вона (можна кілька варіантів), і натисни «Готово».",
            reply_markup=scope_keyboard(upload.doc),
        )
        return
    await message.answer(await activation_message(upload.doc, store, llm))


@router.callback_query(F.data.startswith("sc:"))
async def on_scope(callback: CallbackQuery, store: Store, llm: LLM) -> None:
    _, doc_id, code = callback.data.split(":")
    doc = store.get(int(doc_id))
    if not doc or doc.status != "pending" or doc.uploader_id != callback.from_user.id:
        await callback.answer("Цей документ уже оброблено.", show_alert=True)
        return
    if code == "ok":
        if doc.audience.is_empty():
            await callback.answer("Обери хоча б один варіант.", show_alert=True)
            return
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(await activation_message(doc, store, llm))
        await callback.answer()
        return
    store.set_audience(doc.id, toggle(doc.audience, code))
    await callback.message.edit_reply_markup(reply_markup=scope_keyboard(store.get(doc.id)))
    await callback.answer()


# ---------- questions ----------

@router.callback_query(F.data.startswith("q:"))
async def on_place(callback: CallbackQuery, store: Store, llm: LLM, sessions: Sessions, cfg: Config) -> None:
    question = sessions.pop_pending(callback.message.chat.id)
    await callback.answer()
    if not question:
        await callback.message.answer("Нагадай, будь ласка, питання ще раз 🐭")
        return
    mitten = MITTENS[int(callback.data.split(":")[1])].name
    await callback.message.edit_reply_markup(reply_markup=None)
    await reply_answer(callback.message, question, store, llm, sessions, cfg,
                       forced_mitten=mitten, header=f"Для рукавички «{mitten}»:")


@router.message(F.text & ~F.text.startswith("/"))
async def on_question(message: Message, store: Store, llm: LLM, sessions: Sessions, cfg: Config) -> None:
    await reply_answer(message, message.text.strip(), store, llm, sessions, cfg)


@router.message()
async def on_other(message: Message) -> None:
    await message.answer("Напиши мені питання текстом або надішли документ (PDF, .docx чи .txt) 🐭")
