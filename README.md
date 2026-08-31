# Brain-dump knowledge base — an Obsidian-like vault with Zettelkasten linking

A personal knowledge system built around frictionless capture. Send any text
**or voice** note — ideas, tasks, reminders, thoughts — and it's transcribed (if
voice), enriched by an LLM (type / title / vault path / tags / priority /
reminder), stored in PostgreSQL, and made semantically searchable. Ask it
questions and it answers from your notes (RAG); ask "what do I have to do today?"
and it scopes to reminders due.

It's designed to work like an **Obsidian vault**: every note is filed under a
single folder-style `path` (a controlled vocabulary of existing plus predefined
default folders such as `Inbox`, `projects`, `areas`, `knowledge`), carries tags,
and is meant to export to an Obsidian-style vault (frontmatter + folders +
`[[wikilinks]]`). On top of that it adds **Zettelkasten**-style knowledge
linking: after enrichment you can connect a note to related notes (semantic
nearest neighbours re-ranked by shared path/tags), building a directed graph of
ideas with backlinks — human-curated, not auto-generated.

The Telegram bot is one client adapter; the same domain layer is fronted by a
separate API service (`api/`) so a web or iOS client can reuse it.

Every message is saved with a timestamp. Voice notes are transcribed with OpenAI (`whisper-1`, using a
transcription-context prompt); the raw audio is uploaded to S3-compatible object
storage (Railway bucket / R2 / S3) and the message keeps only the object key.
Each message's text is split into chunks that are embedded with OpenAI and stored
in `note_chunks` (pgvector), powering semantic search via `/search`.

## Project layout

Each module has a single responsibility; the Telegram bot is only the UI layer.

Client adapters live under `capture/` (the Telegram bot in
`capture/Telegram_Bot/`) and `browser/` (the React Mini App in `browser/webapp/`).
The API gateway is `api/`, organised into **section verticals** — one folder per
concern, each with its own `endpoints.py` (router) + `helper.py` (service) +
`db.py` (SQL). Every vertical is self-contained — there is **no shared domain
layer**; each duplicates the domain + persistence it needs. Only true infra is
shared, at the root.

| module            | responsibility                                             |
|-------------------|------------------------------------------------------------|
| `capture/Telegram_Bot/bot.py`        | Telegram handlers, command menu, reminder dispatcher loop  |
| `capture/Telegram_Bot/api_client.py` | async client the bot uses to call `/api/telegram_bot/*` |
| `api/`            | FastAPI gateway service (own Railway service); owns migrations |
| `api/<section>/`  | one isolated vertical per web-app section: `feed`, `browser`, `notesheet`, `notecard`, `mapview`, `contextmenu`, `header`, `search` |
| `api/chat/`       | agentic chat tab (`/api/chat`) — thin; delegates to `agents/chat` |
| `api/evals/`      | protected agent evaluation runner, result persistence, and metrics |
| `api/telegram_bot/` | every bot endpoint (`/api/telegram_bot/*`); owns its full domain in `helper.py` + `db.py` (capture, enrich, reminders, links, users, RAG) |
| `agents/chat/`    | self-contained chat reasoning engine (`tools`/`loop`/`service` + `domain.py`) |
| `agents/enrich/`  | note creation/move/enrichment action agent (+ `domain.py`) |
| `agents/reminder/`| chat-only reminder parsing/planning/persistence agent |
| **shared infra (root + api):** | |
| `config.py`       | all environment variables / constants, read once           |
| `db.py`           | shared `cursor()` connection helper                         |
| `openai_client.py`| one lazily-created OpenAI client                            |
| `file_store.py`   | S3-compatible object storage client (voice audio + attachments) |
| `i18n.py`, `locales.json` | localization                                       |
| `migrate.py`, `migrations/` | schema migrations (run by the API on startup)    |
| `api/deps.py`     | auth (`current_user`, `require_internal_token`) + identity resolve |
| `api/media_token.py` | short-lived signed tokens for the image proxy           |

Dependencies flow one way: every vertical → shared infra (`db`/`config`/`i18n`/
`openai_client`/`file_store`/`api.deps`/`api.media_token`). No vertical imports
another's domain — each owns its SQL and logic, so a section's behaviour can
change in isolation (the trade-off is deliberate duplication). Imports are
absolute (`from api.<section> import …`, `from agents.<agent> import …`).

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Have a PostgreSQL database with the `pgvector` extension available.
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and fill in `BOT_TOKEN`, `DATABASE_URL`, and
   `OPENAI_API_KEY`:

   ```bash
   cp .env.example .env
   ```

   The same `OPENAI_API_KEY` powers both embeddings and voice transcription.
   Voice uses `whisper-1`, which accepts Telegram's OGG audio directly and
   auto-detects Ukrainian/English (set `OPENAI_STT_LANGUAGE` to force one).
   `OPENAI_STT_PROMPT` supplies optional transcription context to bias the
   spelling of names/terms.

5. Apply database migrations:

   ```bash
   python migrate.py
   ```

6. Run it:

   ```bash
   python -m capture.Telegram_Bot.bot
   ```

Send any text message and the bot replies "Saved ✅". Send a voice note and it
replies with the transcript once saved. Use `/search <query>` to find the most
semantically similar notes (matched at the chunk level, deduped to one row per
note).

## Commands

A localized command menu is registered on startup (the Telegram Menu button).

| command      | what it does                                  |
|--------------|-----------------------------------------------|
| `/start`     | welcome message                               |
| `/help`      | overview of everything the bot can do         |
| `/search`    | semantic search of your notes                 |
| `/reminders` | list upcoming reminders                       |
| `/timezone`  | show/set your timezone                        |
| `/language`  | show/set your language (en/uk)                |
| `/user`      | your current settings (language, tz, reminders)|

## Answers (RAG)

`semantic.answer(user_id, query, ...)` runs the search, then sends the query plus
the retrieved chunks — with their analysis (similarity, reminder time, recency,
source) — to an LLM (`ANSWER_LLM_MODEL`) with a system prompt telling it to pick
the single most relevant note, ground the answer only in the notes, mention any
reminder time, and reply naturally in the user's language. `/search` returns this
generated answer. Returns `None` when nothing is retrieved; on an LLM error it
falls back to the top chunk's text.

## Semantic search results

`semantic.search()` (via `chunk_store.search_chunks`) returns the top-k matching
**chunks**, each as a dict with analytics meant to be handed to an LLM:

`rank`, `similarity` (0–1 cosine), `distance` (raw cosine), `rel_to_top`
(similarity gap behind the #1 hit), `content` (the matched chunk text),
`note_id`, `chunk_id`, `chunk_index`, `chunk_count`, `source_type`,
`created_at`, `remind_at` (the note's next active reminder — the in-range one
when filtering, else `None`), `token_count`, and `metadata`.

Cosine (`<=>`) is used because the HNSW index is `vector_cosine_ops`; similarity
is `1 - distance`. Ranking uses a `ROW_NUMBER()` window over the distance-ordered
top-k.

## Capture and enrichment (brain-dump)

Capture is instant and cheap. When you send a note (text, or voice → transcribed)
the bot immediately chunks + embeds it, saves it, checks for a **reminder**
(keyword-gated LLM call in `api/telegram_bot/helper.py`), and replies "Saved ✅" with three
actions: **🧠 Enrich**, **✂️ Atomize**, and **❌ Cancel**. If it's time-bearing, it
also creates the reminder and confirms with a Cancel button.

**Atomize (Zettelkasten).** A brain-dump often holds several ideas; Zettelkasten
wants one idea per note. Tapping ✂️ Atomize makes a single LLM call
(`atomize.py`) that splits the note into atomic notes, each persisted as a new
plain note and posted with the same three actions — so you enrich, split again,
or cancel each independently. It's non-destructive: the original note is kept, and
if the note is already a single idea nothing is created. **Cancel** deletes a note
only if it has no metadata and no links (a guard against accidental taps on notes
you've enriched or linked).

**Enrichment is deferred and on-demand.** Structuring a dump (PARA/CODE-style
analysis) isn't time-critical, so it only runs when you tap 🧠 Enrich. Then
`enrichment.enrich()` makes one LLM call that returns and stores:

- **type** — idea / task / reminder / note / question / link
- **title** — a short summary in the note's own language
- **path** — a single vault folder path (PARA-style top level), at most two
  levels — a root folder plus one optional sub-folder, e.g.
  `Projects/telegram-bot` — the note's home folder for Obsidian export
- **tags** — 0–5 topic keywords (cross-cutting membership)
- **priority** — low / med / high

Because the note's chunks are already embedded, enrichment first pulls the most
similar *already-enriched* notes (`chunk_store.similar_notes`) and feeds their
metadata to the prompt as few-shot examples, alongside the chat's existing
path/tag vocabulary — so classification stays consistent (it extends the folder
tree instead of inventing parallel folders). The reply is edited to show the
result (`💡 title / 📁 path / 🏷 tags / ⚡ priority`). On failure it degrades to a
plain `note`.

### Links (human-in-the-loop)

After enrichment the note shows a **🔗 Link** button. Tapping it lists the ~5
most related notes (`links.candidates`: semantic nearest neighbours re-ranked
with a boost for a shared `path` or `tags`). Each suggested note is itself a
button — tap it to connect (◻️ → ✅), tap again to disconnect. Selection is
stateless: the note ids ride in the callback data and the ✅ marks live in the
keyboard, so nothing is kept in memory and it survives a restart. Links are
directed and stored in `note_links`; **backlinks are the reverse query**, so
connecting A→B gives B its backlink for free. Nothing is auto-linked — you pick.
(LLM-typed relationship labels and Obsidian `[[…]]` export are a later phase.)

## Reminders

When a note is time-bearing, `reminders.extract_reminder` returns a time, a row
is written to the `reminders` table (`reminder_store.py`), and the bot confirms
with "⏰ Reminder set for …" plus a **Cancel** button, so a misparse can be undone
before it fires. A background loop
inside the bot process polls every `REMINDER_POLL_SECONDS` (default 30) for due
reminders and delivers them with **Snooze** (10m / 1h / Tomorrow) and **Done**
buttons.

Best-practice behaviours baked in:

- **Per-user timezone.** `"tomorrow at 9"` resolves against the chat's own
  timezone. Set it with `/timezone Europe/Kyiv` (stored in `user_settings`);
  until then `REMINDER_TZ` is used.
- **Per-user language.** All bot messages and button labels are localized in
  English and Ukrainian. Set with `/language uk` or `/language en` (stored in
  `user_settings`); until then `BOT_DEFAULT_LOCALE` is used. Translations live in
  `locales.json`; add a language by adding a key there.
- **Idempotent claiming.** The dispatcher claims due rows with
  `UPDATE … WHERE id IN (SELECT … FOR UPDATE SKIP LOCKED)` into a transient
  `sending` status, so two dispatchers never deliver the same reminder twice.
- **Crash recovery.** A row stuck in `sending` past
  `REMINDER_SENDING_STALE_SECONDS` (default 120) is reclaimed and retried.
- **Retry on failure.** A reminder is only marked `done` after it sends; a failed
  send reverts to `scheduled` for the next tick.
- **Catch-up after downtime.** State lives in Postgres, so anything due during a
  restart fires on the next poll — with a "(was due X ago)" note if it's late.

Reminder statuses: `scheduled` (waiting), `postponed` (snoozed to a new time),
`sending` (claimed, being delivered), `done` (delivered), `canceled`.

### Agenda-scoped search

`timeparser.parse_agenda(text, now)` returns a `(start, end, key)` date range or
`None`. A cheap keyword gate triggers on an agenda question ("what do I have to do
today?") **or** an explicit range word ("today", "this week", "weekend", "next 3
days", a weekday, + Ukrainian); anything that passes is parsed by the LLM
(defaulting to today if it can't decide). No rule-based date parsing.

The bot's `/search` handler runs it on the query and, when a range comes back,
passes `remind_start`/`remind_end` into `semantic.search` →
`chunk_store.search_chunks`, which restricts results to chunks whose note has an
active reminder due in that window (via a `LEFT JOIN LATERAL` on `reminders` plus
`WHERE rem.remind_at IS NOT NULL`) and surfaces that `remind_at`. `semantic.search`
stays pure — it only takes the two dates; ordinary queries pass `None`.

Times resolve against `REMINDER_TZ` (default `Europe/Kyiv`). For now this is
detection only — the bot replies with a "📅 Looks like a reminder for …"
preview; nothing is stored or scheduled yet.

## Database migrations

The schema is managed by plain SQL files in `migrations/`, applied in filename
order by `migrate.py`. Applied versions are tracked in the `schema_migrations`
table, so running it repeatedly is safe and only new files are applied.

- Add a change: create the next numbered file, e.g. `migrations/0003_xxx.sql`.
- Apply pending changes: `python migrate.py`.

The **API service** runs `run_migrations()` on startup (its FastAPI lifespan), so
it is the component that brings a fresh database up to date. Client adapters
(`bot.py`) no longer migrate and assume the schema is present — so on a fresh
database the API service must be up before the bot (see `api/README.md`).

## Tables

The data model is decoupled from Telegram: notes belong to a **user**, and a
user *optionally* has a Telegram `chat_id`. The bot resolves `chat_id → user_id`
at the edge (`user_store.get_or_create_user`) and everything internal keys on
`user_id`; the dispatcher resolves `user_id → chat_id` only to deliver.

`users` — one row per user (any UI):

| column   | type        | notes                              |
|----------|-------------|------------------------------------|
| id       | bigserial   | primary key (internal user id)     |
| chat_id  | bigint      | Telegram chat, unique, **optional**|
| username | text        | sender username (nullable)         |
| timezone | text        | IANA name (set via /timezone)      |
| language | text        | `en` / `uk` (set via /language)    |
| created_at / updated_at | timestamptz |                        |

`notes` — one row per received note:

| column     | type         | notes                      |
|------------|--------------|----------------------------|
| id         | serial       | primary key                |
| user_id    | bigint       | FK → `users(id)`           |
| text        | text        | message body (transcript for voice) |
| source_type | text        | `'text'` or `'voice'`               |
| audio_key   | text        | S3 object key of the audio (voice only) |
| audio_mime  | text        | audio MIME type (voice only)        |
| note_type   | text        | idea/task/reminder/note/question/link |
| title       | text        | short LLM summary                   |
| priority    | text        | low / med / high                    |
| tags        | jsonb       | topic keywords                      |
| path        | text        | vault folder path (Obsidian home)   |
| created_at  | timestamptz | defaults to `now()`                 |

`note_chunks` — normalized chunks of a note (1:N), embedded and searched
at chunk granularity:

| column      | type         | notes                                   |
|-------------|--------------|-----------------------------------------|
| id          | serial       | primary key                             |
| note_id     | integer      | FK → `notes(id)`, `ON DELETE CASCADE`|
| chunk_index | integer      | order of the chunk within its note   |
| content     | text         | normalized chunk text                   |
| token_count | integer      | optional token count                    |
| metadata    | jsonb        | arbitrary chunk metadata                |
| embedding   | vector(1536) | embedding of the chunk                  |
| created_at  | timestamptz  | defaults to `now()`                     |

`reminders` — reminders parsed from notes:

| column     | type        | notes                                            |
|------------|-------------|--------------------------------------------------|
| id         | serial      | primary key                                      |
| note_id    | integer     | FK → `notes(id)`, `ON DELETE CASCADE` (text comes from here) |
| user_id    | bigint      | FK → `users(id)` (owner; chat resolved for delivery) |
| remind_at  | timestamptz | when it should fire                              |
| status     | text        | scheduled / postponed / sending / done / canceled |
| created_at | timestamptz | defaults to `now()`                              |
| updated_at | timestamptz | bumped on status change                          |
