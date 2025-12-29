#!/usr/bin/env python3
"""
Slack bot for Strava Agent.

Uses Socket Mode for local development (no public URL needed).
"""

import json
import os
import re
import threading
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from agent import StravaAgent

# Paths
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"


def load_config():
    """Load configuration."""
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


# Load config and initialize app
config = load_config()
app = App(token=config["slack"]["bot_token"])

# Store agents per channel/user for conversation continuity
agents = {}
agents_lock = threading.Lock()


def get_agent(channel_id: str) -> StravaAgent:
    """Get or create an agent for a channel."""
    with agents_lock:
        if channel_id not in agents:
            agents[channel_id] = StravaAgent()
        return agents[channel_id]


def clear_agent(channel_id: str):
    """Clear agent history for a channel."""
    with agents_lock:
        if channel_id in agents:
            agents[channel_id].clear_history()


@app.event("app_mention")
def handle_mention(event, say, client):
    """Handle @mentions of the bot."""
    channel = event["channel"]
    thread_ts = event.get("thread_ts", event["ts"])
    user = event["user"]

    # Extract the question (remove the bot mention)
    text = re.sub(r"<@[A-Z0-9]+>", "", event["text"]).strip()

    if not text:
        say(
            text="Ask me anything about your Strava activities! For example:\n"
            "- What was my longest run this year?\n"
            "- How many miles did I bike in December?\n"
            "- What's my average pace for 10k runs?",
            thread_ts=thread_ts,
        )
        return

    # Handle special commands
    if text.lower() in ["clear", "reset", "start over"]:
        clear_agent(channel)
        say(text="Conversation cleared. What would you like to know?", thread_ts=thread_ts)
        return

    if text.lower() in ["help", "?"]:
        say(
            text="*Strava Agent Help*\n\n"
            "Just ask me questions about your Strava activities!\n\n"
            "*Example questions:*\n"
            "- What was my longest run this year?\n"
            "- Compare my mileage this month vs last month\n"
            "- What's my average heart rate on runs over 10 miles?\n"
            "- Show me my fastest 5k\n"
            "- How much elevation did I climb in 2024?\n\n"
            "*Commands:*\n"
            "- `clear` - Reset conversation history\n"
            "- `help` - Show this message",
            thread_ts=thread_ts,
        )
        return

    # Send typing indicator / initial response
    initial = say(text="Thinking...", thread_ts=thread_ts)

    def update_status(status: str):
        """Update the message with current status."""
        try:
            client.chat_update(
                channel=channel,
                ts=initial["ts"],
                text=f"_{status}_",
            )
        except Exception:
            pass  # Ignore update errors

    # Get or create agent for this channel
    agent = get_agent(channel)

    try:
        # Get the answer
        answer = agent.ask(text, on_update=update_status)

        # Update with final answer
        client.chat_update(
            channel=channel,
            ts=initial["ts"],
            text=answer,
        )

    except Exception as e:
        client.chat_update(
            channel=channel,
            ts=initial["ts"],
            text=f"Sorry, I encountered an error: {str(e)}",
        )


@app.event("message")
def handle_dm(event, say, client):
    """Handle direct messages to the bot."""
    # Only respond to DMs (channel type 'im')
    if event.get("channel_type") != "im":
        return

    # Ignore bot messages
    if event.get("bot_id"):
        return

    channel = event["channel"]
    text = event.get("text", "").strip()

    if not text:
        return

    # Handle special commands
    if text.lower() in ["clear", "reset", "start over"]:
        clear_agent(channel)
        say(text="Conversation cleared. What would you like to know?")
        return

    if text.lower() in ["help", "?"]:
        say(
            text="*Strava Agent Help*\n\n"
            "Just ask me questions about your Strava activities!\n\n"
            "*Example questions:*\n"
            "- What was my longest run this year?\n"
            "- Compare my mileage this month vs last month\n"
            "- What's my average heart rate on runs over 10 miles?\n\n"
            "*Commands:*\n"
            "- `clear` - Reset conversation history\n"
            "- `help` - Show this message"
        )
        return

    # Send typing indicator
    initial = say(text="Thinking...")

    def update_status(status: str):
        try:
            client.chat_update(
                channel=channel,
                ts=initial["ts"],
                text=f"_{status}_",
            )
        except Exception:
            pass

    agent = get_agent(channel)

    try:
        answer = agent.ask(text, on_update=update_status)
        client.chat_update(
            channel=channel,
            ts=initial["ts"],
            text=answer,
        )
    except Exception as e:
        client.chat_update(
            channel=channel,
            ts=initial["ts"],
            text=f"Sorry, I encountered an error: {str(e)}",
        )


def main():
    """Start the bot."""
    print("Starting Strava Agent Slack Bot...")
    print("The bot will respond to:")
    print("  - @mentions in channels")
    print("  - Direct messages")
    print("\nPress Ctrl+C to stop.\n")

    handler = SocketModeHandler(app, config["slack"]["app_token"])
    handler.start()


if __name__ == "__main__":
    main()
