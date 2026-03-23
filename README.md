# FreelanceRadar

Self-hosted monitoring bot that watches freelance platforms and sends Telegram notifications for new projects matching your criteria.

> Currently supports **Kwork**. The adapter architecture makes it easy to add other platforms.

## Features

- Polls for new projects every N seconds (configurable)
- Filters by keywords and categories
- Scores projects by relevance
- Sends rich Telegram notifications with project details
- Startup sweep — catches projects posted while the bot was offline

## Quick Start

```bash
git clone https://github.com/CynepMyx/freelance-radar
cd freelance-radar
cp app.env.example app.env
# Edit app.env with your credentials
docker compose up -d
```

## Configuration

Copy `app.env.example` to `app.env` and fill in:

| Variable | Description |
|---|---|
| `KWORK_LOGIN` | Your Kwork account email |
| `KWORK_PASSWORD` | Your Kwork account password |
| `TELEGRAM_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID to send notifications to |
| `KEYWORDS` | Comma-separated keywords to filter projects |
| `POLL_INTERVAL` | Polling interval in seconds (default: 120) |
| `SCORE_THRESHOLD` | Minimum score to trigger notification (default: 5) |
| `OPENROUTER_API_KEY` | OpenRouter API key for AI scoring |
| `REDIS_URL` | Redis connection URL |
| `PG_DSN` | PostgreSQL connection string |

## Architecture

Adapter-based design — each platform is a separate module under `adapters/`:

```
adapters/
  __init__.py
  kwork.py       # Kwork adapter (current)
  # upwork.py   # future
  # fl.ru.py    # future
```

`monitor.py` imports `KworkApi` from `adapters.kwork` — swapping platforms means changing one import.

## Requirements

- Docker + Docker Compose
- Telegram bot token
- Kwork account
- OpenRouter API key (for AI scoring)

## License

MIT
