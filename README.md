# Telegram → PostgreSQL notes bot (POC)

Saves every text **and voice** message sent to the bot into PostgreSQL with a
timestamp. Voice notes are transcribed with Google Speech-to-Text and the raw
audio is kept. Each message's text is split into chunks that are embedded with
OpenAI and stored in `message_chunks` (pgvector), powering semantic search via
`/search`.

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Have a PostgreSQL database with the `pgvector` extension available.
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and fill in `BOT_TOKEN`, `DATABASE_URL`,
   `OPENAI_API_KEY`, and (for voice) `GOOGLE_STT_API_KEY` / `STT_LANGUAGE_CODE`:

   ```bash
   cp .env.example .env
   ```

   The Google API key needs the Cloud Speech-to-Text API enabled. Voice notes
   are sent as OGG/Opus. `STT_LANGUAGE_CODE` is the primary language (default
   `uk-UA`); `STT_ALTERNATE_LANGUAGES` lists up to 3 extra languages Google
   auto-detects (default `en-US`), so Ukrainian and English are both recognized.

5. Apply database migrations:

   ```bash
   python migrate.py
   ```

6. Run it:

   ```bash
   python bot.py
   ```

Send any text message and the bot replies "Saved ✅". Send a voice note and it
replies with the transcript once saved. Use `/search <query>` to find the most
semantically similar notes (matched at the chunk level, deduped to one row per
note).

## Reminder detection (extraction only)

`reminders.py` detects whether a message asks to be reminded and extracts the
time. It first checks cheaply whether the message looks time-bearing; if so it
resolves the phrase locally, using the multilingual [`dateparser`] library for
the date/relative anchor (tomorrow/today, weekdays, "in N minutes"/"через N
годин") while the time-of-day is set by us so part-of-day words get sensible
defaults: morning/вранці → 09:00, afternoon/вдень → 15:00, evening/ввечері →
19:00, night/вночі → 21:00; a bare date defaults to 09:00. Only when it looks
time-bearing but the rules can't pin a time does it fall back to the LLM.

[`dateparser`]: https://dateparser.readthedocs.io/

Times resolve against `REMINDER_TZ` (default `Europe/Kyiv`). For now this is
detection only — the bot replies with a "📅 Looks like a reminder for …"
preview; nothing is stored or scheduled yet.

## Database migrations

The schema is managed by plain SQL files in `migrations/`, applied in filename
order by `migrate.py`. Applied versions are tracked in the `schema_migrations`
table, so running it repeatedly is safe and only new files are applied.

- Add a change: create the next numbered file, e.g. `migrations/0003_xxx.sql`.
- Apply pending changes: `python migrate.py`.

`bot.py` also calls `run_migrations()` on startup, so a fresh deploy sets itself
up automatically. On Railway you can alternatively set `python migrate.py` as a
pre-deploy command.

## Tables

`messages` — one row per received message:

| column     | type         | notes                      |
|------------|--------------|----------------------------|
| id         | serial       | primary key                |
| chat_id    | bigint       | Telegram chat id           |
| username   | text         | sender username (nullable) |
| text        | text        | message body (transcript for voice) |
| source_type | text        | `'text'` or `'voice'`               |
| audio       | bytea       | raw audio bytes (voice only)        |
| audio_mime  | text        | audio MIME type (voice only)        |
| created_at  | timestamptz | defaults to `now()`                 |

`message_chunks` — normalized chunks of a message (1:N), embedded and searched
at chunk granularity:

| column      | type         | notes                                   |
|-------------|--------------|-----------------------------------------|
| id          | serial       | primary key                             |
| message_id  | integer      | FK → `messages(id)`, `ON DELETE CASCADE`|
| chunk_index | integer      | order of the chunk within its message   |
| content     | text         | normalized chunk text                   |
| token_count | integer      | optional token count                    |
| metadata    | jsonb        | arbitrary chunk metadata                |
| embedding   | vector(1536) | embedding of the chunk                  |
| created_at  | timestamptz  | defaults to `now()`                     |
