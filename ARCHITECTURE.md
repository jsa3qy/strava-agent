# Strava Agent Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                   SLACK                                      │
│  ┌─────────────┐                                                            │
│  │   User      │                                                            │
│  │  @strava-agent what was my longest run?                                  │
│  └──────┬──────┘                                                            │
│         │                                                                   │
│         ▼                                                                   │
│  ┌─────────────┐         WebSocket (Socket Mode)                           │
│  │   Slack     │◀─────────────────────────────────────┐                    │
│  │   Cloud     │──────────────────────────────────────┼──────────┐         │
│  └─────────────┘                                      │          │         │
└───────────────────────────────────────────────────────┼──────────┼─────────┘
                                                        │          │
                                                        │          │
┌───────────────────────────────────────────────────────┼──────────┼─────────┐
│                           LOCAL MACHINE               │          │         │
│                                                       │          │         │
│  ┌────────────────────────────────────────────────────┴──────────┴───┐     │
│  │                        slack_bot.py                               │     │
│  │  • Receives events via WebSocket (xapp- token)                    │     │
│  │  • Authenticates with bot token (xoxb-)                           │     │
│  │  • Routes messages to agent                                       │     │
│  │  • Sends responses back to Slack                                  │     │
│  └─────────────────────────────┬─────────────────────────────────────┘     │
│                                │                                           │
│                                ▼                                           │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                         agent.py                                  │     │
│  │  • Manages conversation with Claude API                           │     │
│  │  • Provides tools: execute_sql, execute_python, create_module     │     │
│  │  • Executes generated code in sandbox                             │     │
│  │  • Handles tool call loops until answer is ready                  │     │
│  └───────────┬───────────────────┬───────────────────┬───────────────┘     │
│              │                   │                   │                     │
│              ▼                   ▼                   ▼                     │
│  ┌───────────────────┐ ┌─────────────────┐ ┌─────────────────────┐         │
│  │  Claude API       │ │  SQLite DB      │ │  modules/           │         │
│  │  (Anthropic)      │ │                 │ │                     │         │
│  │                   │ │  activities.db  │ │  registry.json      │         │
│  │  • Understands    │ │  • All Strava   │ │  • Tracks reusable  │         │
│  │    questions      │ │    activities   │ │    query modules    │         │
│  │  • Writes SQL     │ │  • Indexed for  │ │                     │         │
│  │  • Writes Python  │ │    fast queries │ │  *.py modules       │         │
│  │  • Decides when   │ │                 │ │  • Auto-generated   │         │
│  │    to save module │ │                 │ │  • Committed via PR │         │
│  └───────────────────┘ └────────┬────────┘ └─────────────────────┘         │
│                                 │                                          │
│                                 │ Populated by                             │
│                                 ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                      strava_sync.py                               │     │
│  │  • OAuth with Strava API                                          │     │
│  │  • Fetches all activities (paginated)                             │     │
│  │  • Incremental updates (only new activities)                      │     │
│  │  • Stores in SQLite with full metadata                            │     │
│  └───────────────────────────────┬───────────────────────────────────┘     │
│                                  │                                         │
└──────────────────────────────────┼─────────────────────────────────────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │    Strava API       │
                        │                     │
                        │  • OAuth 2.0        │
                        │  • /athlete/        │
                        │    activities       │
                        └─────────────────────┘
```

## Data Flow

### Query Flow (User asks a question)

```
1. User @mentions bot in Slack
           │
           ▼
2. slack_bot.py receives event via WebSocket
           │
           ▼
3. agent.py builds prompt with:
   • System prompt (context/system_prompt.md)
   • Available modules (modules/registry.json)
   • Database stats
   • Conversation history
           │
           ▼
4. Claude API receives prompt + tools
           │
           ▼
5. Claude decides which tool to use:
   ├─► execute_sql    → Run SQL query against activities.db
   ├─► execute_python → Run Python script for complex analysis
   ├─► create_module  → Save reusable code + create PR
   └─► list_modules   → Show available modules
           │
           ▼
6. Tool executes, result returned to Claude
           │
           ▼
7. Claude may call more tools or return final answer
           │
           ▼
8. Answer sent back to Slack
```

### Sync Flow (Update activities)

```
1. Run: python strava_sync.py
           │
           ▼
2. Authenticate with Strava (OAuth)
   • Uses saved tokens if valid
   • Refreshes if expired
   • Full OAuth flow if needed
           │
           ▼
3. Fetch activities from Strava API
   • Paginated (100 per request)
   • Rate limit handling
           │
           ▼
4. Upsert into SQLite
   • 35+ fields per activity
   • Full JSON stored for future use
           │
           ▼
5. Log sync in sync_log table
```

## File Structure

```
strava-agent/
├── slack_bot.py          # Slack interface
├── agent.py              # Claude agent + tools
├── strava_sync.py        # Strava → SQLite sync
│
├── config.json           # Credentials (gitignored)
├── config.example.json   # Template
├── strava_tokens.json    # OAuth tokens (gitignored)
│
├── db/
│   └── activities.db     # SQLite database (gitignored)
│
├── modules/
│   ├── __init__.py       # Module utilities
│   ├── registry.json     # Module manifest
│   └── *.py              # Generated query modules
│
├── context/
│   └── system_prompt.md  # Agent instructions + schema
│
└── requirements.txt      # Python dependencies
```

## Database Schema

```sql
activities
├── id                    # Strava activity ID (PK)
├── name                  # "Morning Run"
├── type                  # Run, Ride, Swim, etc.
├── sport_type            # TrailRun, MountainBikeRide, etc.
├── start_date            # UTC timestamp
├── start_date_local      # Local timestamp
├── timezone              # User's timezone
├── distance              # meters
├── moving_time           # seconds
├── elapsed_time          # seconds (includes stops)
├── total_elevation_gain  # meters
├── average_speed         # m/s
├── max_speed             # m/s
├── average_heartrate     # bpm
├── max_heartrate         # bpm
├── suffer_score          # Strava's "Relative Effort"
├── calories              # kcal
├── ...                   # 20+ more fields
└── raw_json              # Full API response
```

## Security Notes

- **Tokens stored locally** - config.json and strava_tokens.json are gitignored
- **No public endpoints** - Socket Mode means no exposed URLs
- **Code execution sandboxed** - Python runs in subprocess with timeout
- **Read-only SQL** - Only SELECT queries allowed
