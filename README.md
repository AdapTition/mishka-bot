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
| `LLM_BASE_URL` | no | OpenAI-compatible endpoint (Groq by default; a local Ollama can be used) |

On first start the bot loads the "Forest Archive" from `data/archive` (78 documents; 19 scans are recognised via
Tesseract, which takes about a minute). The database is kept in the Docker volume `bot-storage`.

## Usage

- **Question**: any text, e.g. "When are the dues for Under the Oak payable?", "What to do in case of fire?".
- **New document**: send a PDF, .docx or .txt. A new version of a document for the same place replaces the old one.
- `/docs`: all documents grouped by place; `/my`: my documents (these can be deleted).

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
- **Scans** (`bot/extract.py`): PDF pages without a text layer are rendered and recognised by Tesseract (`ukr`).
  Background is cut off by a threshold, junk lines are dropped.
- **Version replacement**: same audience + similar title; in doubtful cases the LLM decides.
- **Groq limits**: two requests per question, on different models (Groq limits are per model); on a 429 the bot
  switches to a fallback model. If the understanding step is unavailable, plain search is used.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests check the classification of all 78 archive documents, place detection in questions, advice priorities and search.
