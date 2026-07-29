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
   are sent as OGG/Opus; `STT_LANGUAGE_CODE` defaults to `uk-UA`.

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
