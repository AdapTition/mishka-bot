# Mishka's Guide: a Telegram bot for forest advice

A bot for the eight mitten-HOAs of the forest. Animals ask questions, and the bot finds the answer in the advice
documents (PDF, Word, TXT, including scans), takes into account which place each piece of advice was written for,
and names the source document. Animals can send in new documents: the bot works out who a document is for, asks
the sender if it is unclear, and replaces outdated versions.

The requirements gathered in conversation with the client, and the decisions made, are in [REQUIREMENTS.md](REQUIREMENTS.md).
The bot talks to users in Ukrainian, as does the document archive.

## Running

Only Docker is required (Docker Desktop, or Docker Engine with the Compose plugin). No local Python needed.

```bash
cp .env.example .env   # Windows (cmd): copy .env.example .env
# open .env and set TG_KEY (token from @BotFather) and GROQ_KEY (key from console.groq.com)
docker compose up -d --build
docker compose logs -f bot   # first start takes ~1-2 min (OCR of scans)
```

Stop with `docker compose down` (the database stays in a volume; `docker compose down -v` removes it too).
Tokens are passed only through environment variables (the `.env` file is in `.gitignore` and never enters the repository).
A Telegram token can be used by only one running bot instance at a time.

| Variable | Required | Description |
|---|---|---|
| `TG_KEY` | yes | bot token from @BotFather |
| `GROQ_KEY` | yes | API key from console.groq.com (free tier) |
| `LLM_MODEL` | no | main model, default `openai/gpt-oss-120b` |
| `LLM_FALLBACK_MODEL` | no | comma-separated fallback models, tried in turn on rate limits, default `qwen/qwen3.8-27b,openai/gpt-oss-20b` |
| `LLM_ROUTER_MODEL` | no | model for the message-understanding step, default `qwen/qwen3.8-27b` |
| `LLM_REASONING_EFFORT` | no | reasoning effort for reasoning models, default `low` (comparisons use `medium`); empty to turn off, e.g. for Ollama |
| `LLM_BASE_URL` | no | OpenAI-compatible endpoint (Groq by default; a local Ollama can be used) |

On first start the bot loads the "Forest Archive" from `data/archive` (78 documents; 19 scans are recognised via
Tesseract, which takes about a minute). The database is kept in the Docker volume `bot-storage`.

## Usage

- **Question**: any text, e.g. "When are the dues for Under the Oak payable?", "What to do in case of fire?".
- **New document**: send a PDF, .docx or .txt. A new version of a document for the same place replaces the old one.
- `/docs`: all documents grouped by place; `/my`: my documents (these can be deleted). Deleting a new version
  brings back the version it replaced, so an archive document cannot be removed by replacing it.

## How it works

```
message + recent turns + document catalogue
   ──► understanding step (qwen3.8-27b): question or chat, standalone question, place, synonyms, catalogue documents
   ──► document selection: catalogue choice + BM25 over synonyms; documents for the animal's place go first
   ──► answer (gpt-oss-120b) from these documents only ──► the bot appends sources (and who sent the document)
```

Documents of other mittens are not discarded: if the question is about them ("Who repairs the dam?"), the bot
answers and says where the information comes from. Such a document is never presented as advice for the
animal's own place.

- **Forest map** (`bot/forest.py`): 3 parts of the forest; "Under the Willow" belongs to two parts, "At the Forest
  Edge" to none. Advice for a mitten outranks advice for a forest part, which outranks general advice.
- **Who a document is for** (`bot/scope.py`): explicit cues in the title and intro first (rules), then the LLM.
  If it is unclear, the bot asks the sender with buttons and does not guess.
- **Scans** (`bot/extract.py`): PDF pages without a text layer are rendered and recognised by Tesseract (`ukr+eng`, so digits are not read as Cyrillic letters).
  Background is cut off by a threshold, junk lines are dropped.
- **Version replacement**: same audience + similar title; in doubtful cases the LLM decides.
- **Groq limits**: two requests per question, on different models (Groq limits are per model); on a 429 the bot
  switches to a fallback model. If the understanding step is unavailable, plain search is used.

## Design decisions and trade-offs

- **Why not put the whole archive into one prompt.** The archive is small (about 50 thousand characters), and
  a model with a large context could read all of it at once. But the free Groq tier allows 8,000 tokens per minute
  per model, and each of the two steps of a question already takes about 3,500 tokens. So the bot selects up to 8 documents (11 for
  comparisons). With a paid model, most of the selection logic could be dropped.
- **Why two models.** Understanding a message (follow-ups, the animals' own words, place, chat or question)
  is a simpler task than a careful answer, and Groq counts limits per model: the light model takes this step
  and the main model's limit is kept for answers. The same pattern (query rewriting before retrieval) is common
  in RAG systems.
- **Why BM25 and not embeddings.** Groq has no embedding models, the corpus is tiny, and the understanding step
  already expands the query with synonyms in the documents' terms. The LLM also picks documents from the
  catalogue by title, which covers the cases where words do not match at all.
- **Why rules before the LLM for "who a document is for".** The client asked not to guess. Explicit phrases
  ("для мешканців хвойного лісу", a mitten in the title) are found deterministically and covered by tests on all
  78 archive documents; the LLM only handles the rest, and is told to answer "unknown" when unsure. For an
  uploaded document, "unknown" means the bot asks the sender. An archive document has no sender, so if one were
  unclear it would be treated as advice for the whole forest (with a warning in the log); none currently is.
- **Known limitations.**
  - Comparisons gather the same kind of document for every mitten by similar titles ("Членські внески
    рукавички …"), so they rely on documents being named alike.
  - A question whose answer is spread across several kinds of documents (e.g. "where do most animals
    hibernate?") may get an incomplete answer. Sending relevant paragraphs instead of whole documents would fix
    this within the same token limit.
  - The free tier handles about 3 questions per minute and about 50 answers per day on the main model; after
    that the fallback models answer.
  - When a mitten has its own document on a topic, the bot answers from it and may leave out the advice of its
    forest parts. For "Під вербою" this means the deciduous-forest and river advice is not always shown next to
    it ([screenshot 03](docs/screenshots/03-edge-willow-beaver.jpg), dangers).
  - Conversations are kept in memory and are lost on restart; documents are kept in SQLite.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests check the classification of all 78 archive documents, place detection in questions, advice priorities, search, LLM fallbacks on rate limits and restoring a replaced document on deletion.

## Manual testing in Telegram

Screenshots from a run of the bot (the tester's name is hidden; the "@" shows where the bot names the sender).

| Scenario | Screenshot |
|---|---|
| Answer with a source; place not named, so the bot asks for the mitten | [01](docs/screenshots/01-fire-and-place-buttons.jpg) |
| Follow-up ("А в дубах?"); advice for the mitten's forest part, the general calendar added | [02](docs/screenshots/02-follow-up-and-priority.jpg) |
| Mitten with no forest part (На узліссі); the place found from an animal's name ("Скільки платить бобер?") | [03](docs/screenshots/03-edge-willow-beaver.jpg) |
| Comparing all mittens (dues in different units, residents' meetings) | [04](docs/screenshots/04-comparison-fees.jpg), [05](docs/screenshots/05-comparison-meetings.jpg) |
| Today's weekday for the ford rule; no invented answer; prompt-injection attempts | [06](docs/screenshots/06-date-and-provocations.jpg) |
| Unclear document: the bot asks the sender instead of guessing | [07](docs/screenshots/07-unclear-document-asks-sender.jpg), [08](docs/screenshots/08-unclear-document-added.jpg) |
| Word document, the sender is named in the sources | [09](docs/screenshots/09-docx-upload.jpg) |
| A new version replaces the old one; deleting it brings the old one back | [10](docs/screenshots/10-new-version-replaces-old.jpg), [11](docs/screenshots/11-delete-restores-old-version.jpg) |

### Found during testing and fixed

- **Deleting a new version lost the archive document.** After deleting the replacement the old version stayed
  hidden, and the bot said there was no information about dues ([before](docs/screenshots/bug-1-before-fix-delete-lost-archive-doc.png),
  [after](docs/screenshots/11-delete-restores-old-version.jpg)). Deletion now brings back the replaced version;
  covered by `tests/test_storage.py`.
- **After choosing a mitten with the buttons, the answer listed all mittens again**
  ([before](docs/screenshots/bug-2-before-fix-chosen-mitten-lists-all.jpg),
  [after](docs/screenshots/12-chosen-mitten-answer.png)). The history held a list over all
  mittens, so the understanding step took the question for a comparison. A chosen mitten now always turns
  comparison mode off; covered by `test_chosen_mitten_is_not_answered_as_comparison`.
