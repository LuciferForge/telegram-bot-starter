# telegram-bot-starter

A Telegram bot with **zero dependencies** — just Python 3. Includes AI chat (Claude/GPT), conversation memory, command system, usage stats, and webhook support. Clone and run.

## Quick Start

```bash
git clone https://github.com/LuciferForge/telegram-bot-starter.git
cd telegram-bot-starter

# Set your bot token (get one from @BotFather on Telegram)
export TELEGRAM_BOT_TOKEN="your-token-here"

# Run the bot
python3 bot.py
```

That's it. Your bot is running.

## Add AI Chat (Optional)

```bash
# Option A: Claude
export ANTHROPIC_API_KEY="sk-ant-..."
python3 bot.py

# Option B: GPT
export OPENAI_API_KEY="sk-..."
python3 bot.py
```

With AI enabled, the bot responds to any message (not just commands) as a conversational AI with memory.

## Built-in Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | List all commands |
| `/echo <text>` | Echo your message back |
| `/ask <question>` | Chat with AI (needs API key) |
| `/clear` | Clear conversation history |
| `/stats` | Bot usage statistics |

## Add Your Own Commands

```python
@command("weather", "Get the weather")
def cmd_weather(msg, args, db):
    city = args or "London"
    # Your logic here
    return f"Weather in {city}: sunny, 22°C"
```

Add the function to `bot.py` — it's automatically registered and appears in `/help`.

## Features

- **Zero dependencies** — uses only Python standard library
- **AI chat** — Claude or GPT, with conversation memory (SQLite)
- **Command system** — decorator-based, auto-registered, easy to extend
- **Conversation memory** — remembers context across messages per chat
- **Usage stats** — tracks commands, users, and activity
- **Webhook support** — for deployment on Railway, Fly, Render, etc.
- **Graceful shutdown** — handles SIGINT/SIGTERM cleanly
- **Markdown support** — bot responses render as formatted text
- **Auto-fallback** — if markdown fails, retries as plain text
- **Single file** — everything in `bot.py`, easy to understand and modify

## Deployment

### Local / VPS (Long Polling)
```bash
export TELEGRAM_BOT_TOKEN="xxx"
python3 bot.py
```

### Railway / Render / Fly (Webhook)
```bash
export TELEGRAM_BOT_TOKEN="xxx"
python3 bot.py --webhook https://your-app.railway.app/webhook 8080
```

### Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY bot.py .
CMD ["python3", "bot.py"]
```

```bash
docker build -t mybot .
docker run -e TELEGRAM_BOT_TOKEN=xxx mybot
```

## Configuration

All configuration is via environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from @BotFather |
| `ANTHROPIC_API_KEY` | No | Enables Claude AI chat |
| `OPENAI_API_KEY` | No | Enables GPT AI chat |
| `AI_MODEL` | No | Override AI model (default: claude-sonnet-4-20250514 or gpt-4o-mini) |
| `BOT_SYSTEM_PROMPT` | No | Custom AI personality |

## Customization

### Change the bot's personality
```bash
export BOT_SYSTEM_PROMPT="You are a pirate. Talk like a pirate in every response. Arrr!"
```

### Add persistent data
The bot already creates `bot_data.db` (SQLite). Add your own tables:
```python
def init_db():
    # ... existing tables ...
    db.execute("""
        CREATE TABLE IF NOT EXISTS user_prefs (
            chat_id TEXT PRIMARY KEY,
            timezone TEXT DEFAULT 'UTC',
            language TEXT DEFAULT 'en'
        )
    """)
```

### Handle photos, documents, etc.
Extend `handle_update()` to process other message types:
```python
if msg.get("photo"):
    # Handle photo
    file_id = msg["photo"][-1]["file_id"]
    # Download and process...
```

## Requirements

- Python 3.6+
- No external packages

## License

MIT
