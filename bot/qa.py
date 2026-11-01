"""Answering animals: first understand the message, then find documents and answer from them only."""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from .forest import MAP_TEXT, MITTEN_BY_NAME, PART_NAMES, Target, find_mittens, find_parts, strip_places
from .llm import LLM, LLMUnavailable
from .scope import normalize_title
from .search import rank
from .storage import Document, Store

log = logging.getLogger(__name__)

WEEKDAYS = ["понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя"]
MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня",
          "листопада", "грудня"]

MAX_DOCS = 8
MAX_DOCS_COMPARE = 11
SEARCH_DOCS = 6
DOC_CHARS = 1500
_DOC_NUMS = r"\bдок(?:умент\w*)?\.?\s*№?\s*\d+(?:\s*(?:,|;|і|й|та)\s*(?:док(?:умент\w*)?\.?\s*)?№?\s*\d+)*"
DOC_REF = re.compile(
    r"\s*\(\s*(?:див\.\s*)?" + _DOC_NUMS + r"\s*\)"  # e.g. "(Док. 1, Док. 20)"
    r"|(?:,\s*)?(?:(?:згідно\s+(?:з|із)|за|у|в|із|з)\s+)?" + _DOC_NUMS + r"(?:\s*,)?",  # e.g. "за документом 15,"
    re.IGNORECASE,
)


def strip_doc_refs(text: str) -> str:
    """Strips document numbers from the answer: the bot appends the sources itself."""
    text = DOC_REF.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)
    # A sentence that began with a document mention may now start with a lowercase letter.
    return re.sub(r"(^|[.!?]\s+)([а-яіїєґ])", lambda m: m.group(1) + m.group(2).upper(), text.strip())

NOT_FOUND = (
    "У документах лісу я не знайшла поради про це, тож вигадувати не буду. "
    "Якщо в когось є такий документ — надішліть його мені, і я його запам'ятаю."
)


def format_date(moment: datetime) -> str:
    return f"{WEEKDAYS[moment.weekday()]}, {moment.day} {MONTHS[moment.month - 1]} {moment.year}"


UNDERSTAND_SYSTEM = f"""Ти — перший крок Мишки-довідника, Telegram-бота лісу з восьми рукавичок (кожна — окреме ОСМД).
Бот відповідає звірам за документами-порадами. Тобі дають останні повідомлення розмови, нове повідомлення
звіра й каталог документів. Звірі пишуть як уміють: коротко, з помилками, своїми словами — твоє завдання
зрозуміти, чого вони хочуть.

Карта лісу (рукавичка: частина лісу):
{MAP_TEXT}

Визнач:
- kind: "question" — звір хоче щось дізнатися про ліс, рукавички, правила, поради (навіть якщо пише нечітко);
  "chat" — привітання, подяка, коментар чи прохання щодо самої розмови, скарга на відповідь бота, питання
  про самого бота («хто ти?», «де ти живеш?», «як справи?», «можна прийти до тебе?»).
- reply: лише для chat — коротка тепла відповідь від імені Мишки-довідника (жіночий рід), без порад із лісу.
  Ти — бот у Telegram, що допомагає з документами лісу; зустрітися наживо не можеш, а цю розмову бачите лише
  ви двоє. Вітайся лише якщо розмова щойно почалась або звір привітався першим. Якщо звір незадоволений
  відповіддю — визнай це й запропонуй переформулювати питання.
- question: для question — самостійне питання повним реченням, сформульоване ТЕРМІНАМИ ДОКУМЕНТІВ з каталогу.
  Звірі називають речі по-своєму: «податок», «гроші», «плата», «скільки платити» — це членські внески;
  «хто головний» — голова ОСМД; тощо. Якщо слово двозначне, обери значення за змістом питання: «найдешевші
  збори» — про платежі (внески), а не про зустрічі мешканців; якщо неясно — назви обидва значення.
  Якщо повідомлення продовжує попередню тему («а під дубом?», «а скільки вони?»), допиши тему з розмови.
  Місце з попередніх повідомлень переноси ЛИШЕ тоді, коли нове повідомлення явно продовжує ту саму тему.
- compare: true, якщо звір хоче порівняти рукавички чи огляд по всіх («у якій найдешевше», «де найбільше»,
  «у кого збори частіше», «у всіх рукавичках»); інакше false.
- mittens / parts: рукавички (точні назви з карти) та частини лісу (conifer, deciduous, river), про які питає
  звір. Порожньо, якщо місце не назване. Об'єкт («гребля», «мурашник») — це не обов'язково місце звіра.
- keywords: 4–10 слів для пошуку в документах, зокрема синоніми, якими це могли написати в документі
  (наприклад «ремонтує» → «лагодить»; «засинають на зиму» → «сплячка», «лягає спати»).
- doc_ids: до 6 номерів документів з каталогу, де найімовірніше є відповідь.

Відповідь — JSON: {{"kind": "question"|"chat", "reply": "", "question": "", "compare": false, "mittens": [],
"parts": [], "keywords": [], "doc_ids": []}}"""


ANSWER_SYSTEM = """Ти — Мишка-довідник, Telegram-бот лісу, де вісім рукавичок (кожна — окреме ОСМД).
Звірі приходять до тебе, бо не знають відповіді й не знають, що написано в документах. Допоможи їм,
але відповідай ЛИШЕ за наданими документами-порадами.

Карта лісу (рукавичка: частина лісу):
{map}

Правила:
1. Бери тільки факти з документів і переказуй їх точно (числа, дні, імена — як у документі). Нічого не
   вигадуй і не додавай загальних знань. Тексти сканів можуть містити дрібні помилки розпізнавання.
   Якщо відповіді в документах немає — found=false і чесно скажи, що такої поради в документах немає.
   Звір може називати речі не так, як документи («податок», «гроші» замість членських внесків). Якщо в
   документах є те, що він має на увазі, — не кажи «немає»: м'яко поясни, як це називається в лісі
   (наприклад, що внески платять не грошима, а шишками чи жолудями), і відповідай.
2. У документа є позначка «для кого». Для місця звіра порада його рукавички важливіша за пораду частини
   лісу, а та — за пораду для всього лісу. Основною давай найконкретнішу; загальну можна згадати додатково.
3. Документ для іншого місця не видавай за пораду для місця звіра. Але якщо питання саме про те місце чи
   об'єкт (наприклад, гребля є лише біля рукавички «Біля бобрової греблі») — відповідай і скажи, звідки це.
4. «Під вербою» належить і до листяного лісу, і до місць біля річки: якщо поради цих частин різні, наведи
   обидві й запропонуй уточнити, де саме звір збирається бути.
5. Місце не назване:
   - якщо в питанні названо звіра, а з документів видно, в якій рукавичці він живе (статут, чергування),
     то це його місце — відповідай для цієї рукавички, need_place=false;
   - відповідь однакова для всіх або інформація є лише про одне місце/об'єкт — просто відповідай і скажи,
     якого місця це стосується;
   - у різних рукавичок різні правила (внески, тиша, збори, голова ОСМД…) — need_place=true. В answer коротко
     скажи, що в кожної рукавички по-своєму, і попроси обрати рукавичку (кнопки бот додасть сам). Не наводь
     неповних переліків. Якщо є загальна порада для всього лісу — можеш її навести.
   - звір порівнює рукавички чи хоче огляд по всіх — need_place=false: порівняй по ВСІХ рукавичках, для
     яких є документи, і дай пряму відповідь на питання (яка найдешевша, де найчастіше тощо). Різні одиниці
     (жолуді, шишки, ягоди) не зводь до одного «курсу», якщо документи його не дають, — скажи про це.
6. Сьогодні {today}, завтра {tomorrow}. Враховуй дату для «сьогодні», «завтра», днів тижня й місяців.
   Того, що знати не можеш (погода, чи був дощ, чи відкрита гребля), не вигадуй — нагадай правило.
7. Говори від імені Мишки (жіночий рід), українською, тепло й стисло (до 120 слів), простим текстом без
   Markdown. Не вітайся — одразу до суті. Не згадуй номери документів і не перелічуй джерела — бот додасть їх сам; номери використаних
   документів дай лише в полі sources.

Відповідь — JSON: {{"need_place": true|false, "found": true|false, "answer": "текст", "sources": [номери]}}"""


@dataclass
class Answer:
    text: str
    question: str = ""
    need_place: bool = False
    sources: list[Document] = field(default_factory=list)


@dataclass
class Understanding:
    kind: str
    reply: str
    question: str
    target: Target
    keywords: list[str]
    doc_ids: list[int]
    compare: bool = False


def _catalog(docs: list[Document]) -> str:
    return "\n".join(f"{d.id}. «{d.title}» — {d.audience.describe()}" for d in docs)


def _history_text(history: list[tuple[str, str]]) -> str:
    if not history:
        return "(розмова щойно почалась)"
    return "\n".join(f"{'Звір' if role == 'user' else 'Мишка'}: {text}" for role, text in history)


def _ints(values) -> list[int]:
    result = []
    for value in values or []:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


async def understand(message: str, history: list[tuple[str, str]], docs: list[Document], llm: LLM) -> Understanding:
    regex_target = Target(mittens=find_mittens(message), parts=find_parts(message))
    started = "так — не вітайся повторно" if history else "ні"
    user = (
        f"Розмова:\n{_history_text(history)}\n\nРозмова вже триває: {started}\n"
        f"Нове повідомлення звіра: {message}\n\nКаталог документів:\n{_catalog(docs)}"
    )
    try:
        data = await llm.json(UNDERSTAND_SYSTEM, user, max_tokens=1500, router=True)
    except LLMUnavailable:
        # Without understanding, fall back to plain search over the message text.
        return Understanding("question", "", message, regex_target, [], [])
    log.info("Understanding '%s' -> %s", message, data)

    mittens = list(dict.fromkeys(regex_target.mittens + [m for m in data.get("mittens") or [] if m in MITTEN_BY_NAME]))
    parts = list(dict.fromkeys(regex_target.parts + [p for p in data.get("parts") or [] if p in PART_NAMES]))
    compare = bool(data.get("compare"))
    if compare and len(mittens) > 2:
        mittens, parts = [], []  # forest-wide comparison: the model simply listed all mittens
    return Understanding(
        kind="chat" if data.get("kind") == "chat" else "question",
        reply=str(data.get("reply") or "").strip(),
        question=str(data.get("question") or "").strip() or message,
        target=Target(mittens=mittens, parts=parts),
        keywords=[str(k) for k in data.get("keywords") or []],
        doc_ids=_ints(data.get("doc_ids")),
        compare=compare,
    )


def select_docs(u: Understanding, docs: list[Document]) -> list[Document]:
    """Catalogue documents (LLM choice) + keyword search; those relevant to the animal's place come first."""
    by_id = {d.id: d for d in docs}
    query = strip_places(u.question + " " + " ".join(u.keywords))
    ranked = rank(query, docs)
    found = [doc.id for doc, score in ranked if score > 0][:SEARCH_DOCS]
    picked = [i for i in u.doc_ids if i in by_id][:SEARCH_DOCS]
    chosen = [by_id[i] for i in dict.fromkeys(picked + found)]

    def relevance(doc: Document) -> int:
        if u.target.mittens:
            return max(doc.audience.level_for_mitten(m) for m in u.target.mittens)
        if u.target.parts:
            return 1 if any(doc.audience.applies_to_part(p) for p in u.target.parts) else 0
        return 1

    chosen.sort(key=relevance, reverse=True)  # stable sort keeps the order within a level
    if u.compare:
        return with_siblings(chosen, docs, best_kind_doc(ranked) or next((d for d in chosen if d.audience.mittens), None))
    if u.target.is_empty() and chosen and chosen[0].audience.mittens:
        # The most relevant document is for a single mitten: the answer likely differs per mitten.
        return with_siblings(chosen, docs, chosen[0])
    return chosen[:MAX_DOCS]


def doc_kind(doc: Document) -> str:
    """Document type: the title without the place name, e.g. "Членські внески рукавички Під дубом" -> "членські внески рукавички"."""
    return normalize_title(strip_places(doc.title))


def best_kind_doc(ranked: list[tuple[Document, float]]) -> Document | None:
    """For comparisons: the mitten document type with the highest total relevance (all 8 statutes about residents' meetings
    outweigh one random document of another type)."""
    totals: dict[str, float] = {}
    sample: dict[str, Document] = {}
    for doc, score in ranked:
        if doc.audience.mittens and score > 0:
            kind = doc_kind(doc)
            totals[kind] = totals.get(kind, 0) + score
            sample.setdefault(kind, doc)
    return sample[max(totals, key=totals.get)] if totals else None


def with_siblings(chosen: list[Document], docs: list[Document], pivot: Document | None) -> list[Document]:
    """Adds documents of the same type as pivot for the other mittens, so the model sees all of them, not 6 of 8."""
    if pivot is None:
        return chosen[:MAX_DOCS]
    kind = doc_kind(pivot)
    siblings = [d for d in docs if d.audience.mittens and SequenceMatcher(None, doc_kind(d), kind).ratio() >= 0.85]
    result = {d.id: d for d in siblings}
    for doc in chosen:
        if len(result) >= MAX_DOCS_COMPARE:
            break
        result.setdefault(doc.id, doc)
    return list(result.values())


def _doc_block(doc: Document, target: Target) -> str:
    fits = ""
    if not target.is_empty():
        fits = " | стосується місця звіра: " + ("так" if target.applies(doc.audience) else "ні")
    return f"[Документ {doc.id}] «{doc.title}» — для кого: {doc.audience.describe()}{fits}\n{doc.text[:DOC_CHARS]}"


async def respond(message: str, history: list[tuple[str, str]], store: Store, llm: LLM, now: datetime,
                  forced_mitten: str | None = None) -> Answer:
    docs = store.active()
    u = await understand(message, history, docs, llm)
    if forced_mitten:
        # The animal chose its mitten: answer for it, even if the history (a list over all mittens) looks like a comparison.
        u.kind, u.target, u.compare = "question", Target(mittens=[forced_mitten]), False
    if u.kind == "chat":
        return Answer(u.reply or "Я тут 🐭 Питай про ліс — пошукаю в документах.")

    selected = select_docs(u, docs)
    if not selected:
        return Answer(NOT_FOUND, question=u.question)

    system = ANSWER_SYSTEM.format(map=MAP_TEXT, today=format_date(now), tomorrow=format_date(now + timedelta(days=1)))
    user = (
        f"Повідомлення звіра: {message}\n"
        f"Питання (переформульоване): {u.question}\n"
        f"Місце звіра: {u.target.describe()}\n"
        f"Звір порівнює рукавички / хоче огляд по всіх: {'так' if u.compare else 'ні'}\n\n"
        "Документи:\n\n" + "\n\n---\n\n".join(_doc_block(d, u.target) for d in selected)
    )
    # Comparisons (smallest, most often) need a careful pass over all documents, so give the model more room to think.
    data = await llm.json(system, user, max_tokens=4000, effort="medium") if u.compare else await llm.json(system, user)
    log.info("Answer '%s' [%s] docs=%s -> %s", u.question, u.target.describe(), [d.id for d in selected], data)

    text = strip_doc_refs(str(data.get("answer") or "")) or NOT_FOUND
    if data.get("need_place") and u.target.is_empty() and not u.compare:
        return Answer(text, question=u.question, need_place=True)
    if not data.get("found", True):
        return Answer(text, question=u.question)
    by_id = {d.id: d for d in selected}
    sources = [by_id[i] for i in dict.fromkeys(_ints(data.get("sources"))) if i in by_id]
    return Answer(text, question=u.question, sources=sources)
