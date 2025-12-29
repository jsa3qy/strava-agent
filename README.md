# Strava Agent

A Slack bot powered by Claude that answers questions about your Strava activities.

## Features

- Natural language queries about your Strava data
- SQLite database for fast local queries
- Automatic module creation for reusable query patterns
- Conversation memory within sessions
- Progress updates for long-running queries

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

Copy `config.example.json` to `config.json` and fill in:

```json
{
  "strava": {
    "client_id": "YOUR_STRAVA_CLIENT_ID",
    "client_secret": "YOUR_STRAVA_CLIENT_SECRET"
  },
  "slack": {
    "bot_token": "xoxb-YOUR-BOT-TOKEN",
    "app_token": "xapp-YOUR-APP-TOKEN"
  },
  "anthropic": {
    "api_key": "YOUR_ANTHROPIC_API_KEY"
  }
}
```

### 3. Set up Strava API

1. Go to https://www.strava.com/settings/api
2. Create an application
3. Copy Client ID and Client Secret to config.json

### 4. Set up Slack App

1. Go to https://api.slack.com/apps
2. Create New App → From scratch
3. Enable **Socket Mode** (Settings → Socket Mode → Enable)
   - Generate an app-level token with `connections:write` scope
   - This is your `app_token` (starts with `xapp-`)
4. Add Bot Token Scopes (OAuth & Permissions):
   - `app_mentions:read`
   - `chat:write`
   - `im:history`
   - `im:read`
   - `im:write`
5. Enable Events (Event Subscriptions):
   - Subscribe to: `app_mention`, `message.im`
6. Install to workspace
7. Copy Bot User OAuth Token (starts with `xoxb-`)

### 5. Sync your Strava data

```bash
# Initialize database and sync all activities
python strava_sync.py
```

This will open a browser for Strava authorization on first run.

### 6. Start the bot

```bash
python slack_bot.py
```

## Usage

### In Slack

- **@mention the bot** in any channel: `@StravaAgent what was my longest run?`
- **DM the bot** directly
- Say `clear` to reset conversation history
- Say `help` for example questions

### CLI Testing

```bash
python agent.py
```

## Example Questions

- What was my longest run this year?
- How many miles did I bike in December?
- Compare my running mileage this month vs last year
- What's my average pace for runs over 10 miles?
- Show me my top 5 suffer score activities
- How much elevation did I climb in 2024?

## Architecture

```
slack_bot.py      # Slack interface (Socket Mode)
    ↓
agent.py          # Claude-powered agent with tools
    ↓
db/activities.db  # SQLite database
    ↓
modules/          # Reusable query modules (auto-generated)
```

## Syncing New Activities

Run periodically to fetch new activities:

```bash
python strava_sync.py
```

Or force a full resync:

```bash
python strava_sync.py --force
```
