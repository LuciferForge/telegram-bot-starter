#!/usr/bin/env python3
"""
telegram-bot-starter — Telegram bot with zero dependencies beyond Python.

Setup:
    1. Get a bot token from @BotFather on Telegram
    2. Set your token: export TELEGRAM_BOT_TOKEN="your-token-here"
    3. Run: python3 bot.py

Usage:
    python3 bot.py                    # Run the bot (long polling)
    python3 bot.py --webhook URL      # Run with webhook (for deployment)
    TELEGRAM_BOT_TOKEN=xxx python3 bot.py  # Pass token via env

The bot includes:
    /start   — Welcome message
    /help    — List commands
    /echo    — Echo back your message
    /ask     — AI chat (when AI provider is configured)
    /img     — Describe any image sent to the bot
    /stats   — Bot usage statistics

Add your own commands by adding functions with the @command decorator.
"""

import json
import os
import re
import signal
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread


# ── Configuration ───────────────────────────────────────────────────────

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"

# Optional: AI provider for /ask command
# Set OPENAI_API_KEY or ANTHROPIC_API_KEY to enable AI chat
AI_PROVIDER = None  # auto-detected below
AI_API_KEY = None
AI_MODEL = None

if os.environ.get("ANTHROPIC_API_KEY"):
    AI_PROVIDER = "anthropic"
    AI_API_KEY = os.environ["ANTHROPIC_API_KEY"]
    AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-20250514")
elif os.environ.get("OPENAI_API_KEY"):
    AI_PROVIDER = "openai"
    AI_API_KEY = os.environ["OPENAI_API_KEY"]
    AI_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")

# Bot personality (customize this)
SYSTEM_PROMPT = os.environ.get("BOT_SYSTEM_PROMPT",
    "You are a helpful assistant in a Telegram chat. "
    "Keep responses concise (under 300 words). "
    "Use markdown formatting when helpful."
)

# Database for conversation memory + stats
DB_PATH = Path(__file__).parent / "bot_data.db"


# ── Database ────────────────────────────────────────────────────────────

def init_db():
    """Initialize SQLite database for memory and stats."""
    db = sqlite3.connect(str(DB_PATH))
    db.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT DEFAULT (datetime('now'))
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            command TEXT NOT NULL,
            timestamp TEXT DEFAULT (datetime('now'))
        )
    """)
    db.commit()
    return db


def save_message(db, chat_id, role, content):
    """Save a message to conversation history."""
    db.execute(
        "INSERT INTO conversations (chat_id, role, content) VALUES (?, ?, ?)",
        (str(chat_id), role, content[:2000])
    )
    db.commit()


def get_history(db, chat_id, limit=10):
    """Get recent conversation history for a chat."""
    rows = db.execute(
        "SELECT role, content FROM conversations WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (str(chat_id), limit)
    ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def log_command(db, chat_id, command):
    """Log command usage for stats."""
    db.execute(
        "INSERT INTO stats (chat_id, command) VALUES (?, ?)",
        (str(chat_id), command)
    )
    db.commit()


# ── Telegram API ────────────────────────────────────────────────────────

def tg_request(method, data=None, timeout=30):
    """Make a Telegram Bot API request."""
    url = f"{API}/{method}"
    if data:
        payload = json.dumps(data).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"  Telegram API error ({method}): {e}", file=sys.stderr)
        return None


def send_message(chat_id, text, parse_mode="Markdown", reply_to=None):
    """Send a text message."""
    # Telegram has a 4096 char limit
    if len(text) > 4000:
        text = text[:4000] + "\n\n_...truncated_"
    data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_to:
        data["reply_to_message_id"] = reply_to
    result = tg_request("sendMessage", data)
    # Fallback: if markdown fails, retry without parse_mode
    if not result or not result.get("ok"):
        data["parse_mode"] = None
        tg_request("sendMessage", data)


def send_typing(chat_id):
    """Show 'typing...' indicator."""
    tg_request("sendChatAction", {"chat_id": chat_id, "action": "typing"})


# ── AI Integration ──────────────────────────────────────────────────────

def ask_ai(messages):
    """Send messages to AI provider and get response."""
    if not AI_PROVIDER or not AI_API_KEY:
        return None

    if AI_PROVIDER == "anthropic":
        return _ask_anthropic(messages)
    elif AI_PROVIDER == "openai":
        return _ask_openai(messages)
    return None


def _ask_anthropic(messages):
    """Call Anthropic Claude API."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": AI_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    # Convert to Anthropic format
    api_messages = []
    for m in messages:
        if m["role"] != "system":
            api_messages.append({"role": m["role"], "content": m["content"]})

    data = json.dumps({
        "model": AI_MODEL,
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": api_messages,
    }).encode()

    try:
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return result["content"][0]["text"]
    except Exception as e:
        return f"AI error: {e}"


def _ask_openai(messages):
    """Call OpenAI API."""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AI_API_KEY}",
    }
    all_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    data = json.dumps({
        "model": AI_MODEL,
        "messages": all_messages,
        "max_tokens": 1024,
    }).encode()

    try:
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"AI error: {e}"


# ── Command System ──────────────────────────────────────────────────────

COMMANDS = {}


def command(name, description=""):
    """Decorator to register a bot command."""
    def decorator(func):
        COMMANDS[name] = {"handler": func, "description": description}
        return func
    return decorator


@command("start", "Start the bot")
def cmd_start(msg, args, db):
    user = msg.get("from", {}).get("first_name", "there")
    return (
        f"Hey {user}! I'm a bot built with "
        f"[telegram-bot-starter](https://github.com/LuciferForge/telegram-bot-starter).\n\n"
        f"Send /help to see what I can do."
    )


@command("help", "Show available commands")
def cmd_help(msg, args, db):
    lines = ["*Available Commands*\n"]
    for name, info in COMMANDS.items():
        desc = info["description"] or "No description"
        lines.append(f"/{name} — {desc}")
    if AI_PROVIDER:
        lines.append(f"\n_AI: {AI_PROVIDER} ({AI_MODEL})_")
    else:
        lines.append("\n_AI: not configured (set ANTHROPIC\\_API\\_KEY or OPENAI\\_API\\_KEY)_")
    return "\n".join(lines)


@command("echo", "Echo your message back")
def cmd_echo(msg, args, db):
    if not args:
        return "Usage: /echo <your message>"
    return f"You said: {args}"


@command("ask", "Chat with AI")
def cmd_ask(msg, args, db):
    if not AI_PROVIDER:
        return (
            "AI not configured. Set one of these environment variables:\n"
            "`ANTHROPIC_API_KEY` — for Claude\n"
            "`OPENAI_API_KEY` — for GPT"
        )
    if not args:
        return "Usage: /ask <your question>"

    chat_id = msg["chat"]["id"]
    send_typing(chat_id)

    # Get conversation history for context
    history = get_history(db, chat_id, limit=10)
    history.append({"role": "user", "content": args})

    response = ask_ai(history)
    if response:
        save_message(db, chat_id, "user", args)
        save_message(db, chat_id, "assistant", response)
        return response
    return "Sorry, AI is not available right now."


@command("clear", "Clear conversation history")
def cmd_clear(msg, args, db):
    chat_id = msg["chat"]["id"]
    db.execute("DELETE FROM conversations WHERE chat_id = ?", (str(chat_id),))
    db.commit()
    return "Conversation history cleared."


@command("stats", "Bot usage statistics")
def cmd_stats(msg, args, db):
    total = db.execute("SELECT COUNT(*) FROM stats").fetchone()[0]
    unique = db.execute("SELECT COUNT(DISTINCT chat_id) FROM stats").fetchone()[0]
    today = db.execute(
        "SELECT COUNT(*) FROM stats WHERE timestamp > datetime('now', '-24 hours')"
    ).fetchone()[0]

    # Top commands
    top = db.execute(
        "SELECT command, COUNT(*) as cnt FROM stats GROUP BY command ORDER BY cnt DESC LIMIT 5"
    ).fetchall()
    top_str = "\n".join(f"  /{c}: {n}" for c, n in top) if top else "  None yet"

    return (
        f"*Bot Stats*\n\n"
        f"Total commands: {total}\n"
        f"Unique users: {unique}\n"
        f"Last 24h: {today}\n\n"
        f"*Top commands:*\n{top_str}"
    )


# ── Message Handler ─────────────────────────────────────────────────────

def handle_update(update, db):
    """Process a single Telegram update."""
    msg = update.get("message")
    if not msg:
        return

    text = (msg.get("text") or "").strip()
    chat_id = msg["chat"]["id"]

    # Handle commands
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        cmd_name = parts[0][1:].lower().split("@")[0]  # Remove /prefix and @botname
        args = parts[1] if len(parts) > 1 else ""

        cmd = COMMANDS.get(cmd_name)
        if cmd:
            log_command(db, chat_id, cmd_name)
            try:
                response = cmd["handler"](msg, args, db)
                if response:
                    send_message(chat_id, response)
            except Exception as e:
                send_message(chat_id, f"Error: {e}", parse_mode=None)
                print(f"  Command /{cmd_name} error: {e}", file=sys.stderr)
        else:
            send_message(chat_id, f"Unknown command: /{cmd_name}\nTry /help")
        return

    # Handle plain text — if AI is configured, treat as conversation
    if text and AI_PROVIDER:
        send_typing(chat_id)
        history = get_history(db, chat_id, limit=10)
        history.append({"role": "user", "content": text})

        response = ask_ai(history)
        if response:
            save_message(db, chat_id, "user", text)
            save_message(db, chat_id, "assistant", response)
            send_message(chat_id, response)
            log_command(db, chat_id, "chat")


# ── Polling ─────────────────────────────────────────────────────────────

def run_polling():
    """Long-polling loop."""
    print(f"Bot starting (polling mode)...", file=sys.stderr)
    if AI_PROVIDER:
        print(f"  AI: {AI_PROVIDER} ({AI_MODEL})", file=sys.stderr)
    else:
        print(f"  AI: not configured", file=sys.stderr)

    db = init_db()
    offset = 0

    # Graceful shutdown
    running = True
    def shutdown(sig, frame):
        nonlocal running
        print("\nShutting down...", file=sys.stderr)
        running = False
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    while running:
        try:
            result = tg_request("getUpdates", {
                "offset": offset,
                "timeout": 30,
                "limit": 50,
            }, timeout=35)

            if result and result.get("ok"):
                for update in result.get("result", []):
                    handle_update(update, db)
                    offset = update["update_id"] + 1
        except Exception as e:
            print(f"  Poll error: {e}", file=sys.stderr)
            time.sleep(5)

    db.close()
    print("Bot stopped.", file=sys.stderr)


# ── Webhook ─────────────────────────────────────────────────────────────

class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP handler for Telegram webhook."""
    db = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            update = json.loads(body)
            handle_update(update, self.db)
        except Exception as e:
            print(f"  Webhook error: {e}", file=sys.stderr)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass  # Suppress HTTP logs


def run_webhook(url, port=8443):
    """Run bot with webhook."""
    print(f"Bot starting (webhook mode on port {port})...", file=sys.stderr)
    db = init_db()
    WebhookHandler.db = db

    # Set webhook with Telegram
    tg_request("setWebhook", {"url": url})
    print(f"  Webhook set to {url}", file=sys.stderr)

    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...", file=sys.stderr)
    finally:
        tg_request("deleteWebhook")
        db.close()


# ── Main ────────────────────────────────────────────────────────────────

def main():
    if not TOKEN:
        print("Error: Set TELEGRAM_BOT_TOKEN environment variable", file=sys.stderr)
        print("  Get a token from @BotFather on Telegram", file=sys.stderr)
        print("  Then: export TELEGRAM_BOT_TOKEN='your-token-here'", file=sys.stderr)
        sys.exit(1)

    # Check for webhook mode
    if "--webhook" in sys.argv:
        idx = sys.argv.index("--webhook")
        if idx + 1 < len(sys.argv):
            url = sys.argv[idx + 1]
            port = int(sys.argv[idx + 2]) if idx + 2 < len(sys.argv) else 8443
            run_webhook(url, port)
        else:
            print("Usage: python3 bot.py --webhook https://your-domain.com/webhook [port]", file=sys.stderr)
            sys.exit(1)
    else:
        run_polling()


if __name__ == "__main__":
    main()
