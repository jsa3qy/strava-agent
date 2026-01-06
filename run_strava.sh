#!/bin/bash
# Self-healing wrapper for Strava Agent
# Automatically restarts on crash with exponential backoff

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv if it exists
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
    PYTHON="python"
    echo "Using venv: $SCRIPT_DIR/venv"
elif command -v python3 &> /dev/null; then
    PYTHON="python3"
else
    PYTHON="python"
fi

echo "Using: $PYTHON ($($PYTHON --version 2>&1))"

MAX_RETRIES=10
RETRY_DELAY=5
MAX_DELAY=300  # 5 minutes max

retry_count=0
delay=$RETRY_DELAY

while true; do
    echo "[$(date)] Starting Strava Agent..."

    $PYTHON slack_bot.py
    exit_code=$?

    if [ $exit_code -eq 0 ]; then
        echo "[$(date)] Strava Agent exited cleanly."
        break
    fi

    if [ $exit_code -eq 42 ]; then
        # Special exit code for requested restart
        echo "[$(date)] Restart requested. Restarting immediately..."
        retry_count=0
        delay=$RETRY_DELAY
        sleep 1
        continue
    fi

    retry_count=$((retry_count + 1))
    echo "[$(date)] Strava Agent crashed with exit code $exit_code (attempt $retry_count)"

    if [ $retry_count -ge $MAX_RETRIES ]; then
        echo "[$(date)] Max retries reached. Resetting counter after longer delay..."
        sleep $MAX_DELAY
        retry_count=0
        delay=$RETRY_DELAY
    else
        echo "[$(date)] Restarting in $delay seconds..."
        sleep $delay
        # Exponential backoff
        delay=$((delay * 2))
        if [ $delay -gt $MAX_DELAY ]; then
            delay=$MAX_DELAY
        fi
    fi
done
