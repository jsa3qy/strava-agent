# Raspberry Pi Setup

Run the Strava Agent 24/7 on a Raspberry Pi with zero recurring hosting costs.

## Requirements

- Raspberry Pi (3, 4, or 5)
- MicroSD card (16GB+)
- Power supply
- Network connection (WiFi or Ethernet)

## Step 1: Flash the OS

On your Mac:
```bash
brew install --cask raspberry-pi-imager
```

Or download from https://www.raspberrypi.com/software/

**In the imager:**
1. Choose OS → **Raspberry Pi OS Lite (64-bit)**
2. Choose Storage → your SD card
3. Click gear icon (⚙️) for settings:
   - Enable SSH
   - Set username/password
   - Configure WiFi (if not using Ethernet)
   - Set hostname (e.g., `strava-pi`)
4. Write to card

## Step 2: First Boot & Connect

Insert SD card, power on the Pi, wait ~2 minutes, then:

```bash
# Find the Pi on your network
ping strava-pi.local

# SSH in
ssh pi@strava-pi.local
```

## Step 3: Install Dependencies

Run these on the Pi:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and git
sudo apt install -y python3 python3-pip python3-venv git

# Create project directory
mkdir -p ~/strava-agent
cd ~/strava-agent

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python packages
pip install anthropic slack-bolt requests
```

## Step 4: Clone the Repo

```bash
cd ~
git clone https://github.com/jsa3qy/strava-agent.git
cd strava-agent
```

## Step 5: Configure

```bash
cp config.example.json config.json
nano config.json
```

Add your credentials:
```json
{
  "strava": {
    "client_id": "YOUR_ID",
    "client_secret": "YOUR_SECRET"
  },
  "slack": {
    "bot_token": "xoxb-...",
    "app_token": "xapp-..."
  },
  "anthropic": {
    "api_key": "sk-ant-..."
  }
}
```

Save with `Ctrl+O`, exit with `Ctrl+X`.

## Step 6: Copy or Sync Database

**Option A: Copy existing database from your Mac**
```bash
# Run this on your Mac
scp ~/Beta/strava-agent/db/activities.db pi@strava-pi.local:~/strava-agent/db/
```

**Option B: Sync fresh on the Pi**
```bash
cd ~/strava-agent
source venv/bin/activate
mkdir -p db
python3 strava_sync.py
```

## Step 7: Test

```bash
cd ~/strava-agent
source venv/bin/activate
python3 slack_bot.py
```

Send a message in Slack. If it responds, you're ready for the next step!

Press `Ctrl+C` to stop.

## Step 8: Set Up Auto-Start (systemd)

Create the service file:
```bash
sudo nano /etc/systemd/system/strava-agent.service
```

Paste this (adjust username if not `pi`):
```ini
[Unit]
Description=Strava Agent Slack Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/strava-agent
ExecStart=/home/pi/strava-agent/venv/bin/python3 /home/pi/strava-agent/slack_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Save and exit, then enable:
```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable on boot
sudo systemctl enable strava-agent

# Start now
sudo systemctl start strava-agent

# Check status
sudo systemctl status strava-agent
```

## Step 9: Set Up Daily Sync (cron)

```bash
crontab -e
```

Add this line (syncs at 4am daily):
```
0 4 * * * cd /home/pi/strava-agent && /home/pi/strava-agent/venv/bin/python3 strava_sync.py >> /home/pi/strava-agent/sync.log 2>&1
```

## Useful Commands

```bash
# SSH into Pi
ssh pi@strava-pi.local

# Check if bot is running
sudo systemctl status strava-agent

# Restart bot
sudo systemctl restart strava-agent

# Stop bot
sudo systemctl stop strava-agent

# View live logs
journalctl -u strava-agent -f

# View last 100 log lines
journalctl -u strava-agent -n 100

# Manual sync
cd ~/strava-agent && source venv/bin/activate && python3 strava_sync.py

# Pull latest code and restart
cd ~/strava-agent && git pull && sudo systemctl restart strava-agent

# Check sync log
tail -50 ~/strava-agent/sync.log
```

## Troubleshooting

### Bot won't start
```bash
# Check logs for errors
journalctl -u strava-agent -n 50

# Try running manually to see errors
cd ~/strava-agent
source venv/bin/activate
python3 slack_bot.py
```

### Can't connect to Pi
```bash
# Make sure Pi is on and connected to network
# Try IP address instead of hostname
ssh pi@192.168.1.XXX
```

### Database errors
```bash
# Reinitialize database
cd ~/strava-agent
source venv/bin/activate
python3 strava_sync.py --init
python3 strava_sync.py
```

### Out of disk space
```bash
# Check disk usage
df -h

# Clean up old logs
sudo journalctl --vacuum-time=7d
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    RASPBERRY PI                             │
│                                                             │
│   systemd service (auto-starts on boot)                    │
│   └── slack_bot.py ──► Slack (WebSocket)                   │
│           │                                                 │
│           ▼                                                 │
│       agent.py ──► Claude API                              │
│           │                                                 │
│           ▼                                                 │
│       db/activities.db                                      │
│                                                             │
│   cron job (daily 4am)                                     │
│   └── strava_sync.py ──► Strava API                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Cost Breakdown

| Item | Cost |
|------|------|
| Raspberry Pi 4 (2GB) | ~$45 one-time |
| MicroSD card (32GB) | ~$10 one-time |
| Power supply | ~$10 one-time |
| Electricity (~5W 24/7) | ~$5/year |
| Claude API (usage-based) | $1-10/month |

**First year total: ~$80-185**
**Subsequent years: ~$17-125/year** (just electricity + API)
