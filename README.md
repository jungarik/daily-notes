# Telegram → PostgreSQL notes bot (POC)

Saves every text message sent to the bot into a PostgreSQL table with a timestamp.

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Have a PostgreSQL database ready.
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and fill in your values:

   ```bash
   cp .env.example .env
   ```

5. Run it:

   ```bash
   python bot.py
   ```

The `messages` table is created automatically on first run. Send any text
message to the bot and it replies "Saved ✅" and stores the row.

## Table

| column     | type        | notes                     |
|------------|-------------|---------------------------|
| id         | serial      | primary key               |
| chat_id    | bigint      | Telegram chat id          |
| username   | text        | sender username (nullable)|
| text       | text        | message body              |
| created_at | timestamptz | defaults to `now()`       |
