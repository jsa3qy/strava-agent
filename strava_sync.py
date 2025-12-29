#!/usr/bin/env python3
"""
Sync Strava activities to SQLite database.
Handles OAuth, incremental updates, and full syncs.
"""

import json
import os
import sqlite3
import time
import webbrowser
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

DB_PATH = os.path.join(os.path.dirname(__file__), "db", "activities.db")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
TOKENS_PATH = os.path.join(os.path.dirname(__file__), "strava_tokens.json")


def get_db_connection():
    """Get a connection to the SQLite database."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database schema."""
    conn = get_db_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY,
            name TEXT,
            type TEXT,
            sport_type TEXT,
            start_date TEXT,
            start_date_local TEXT,
            timezone TEXT,
            distance REAL,
            moving_time INTEGER,
            elapsed_time INTEGER,
            total_elevation_gain REAL,
            elev_high REAL,
            elev_low REAL,
            average_speed REAL,
            max_speed REAL,
            average_heartrate REAL,
            max_heartrate REAL,
            average_cadence REAL,
            average_watts REAL,
            weighted_average_watts REAL,
            kilojoules REAL,
            suffer_score INTEGER,
            calories REAL,
            achievement_count INTEGER,
            kudos_count INTEGER,
            comment_count INTEGER,
            athlete_count INTEGER,
            pr_count INTEGER,
            start_latlng TEXT,
            end_latlng TEXT,
            summary_polyline TEXT,
            gear_id TEXT,
            device_name TEXT,
            raw_json TEXT,
            synced_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_type ON activities(type);
        CREATE INDEX IF NOT EXISTS idx_sport_type ON activities(sport_type);
        CREATE INDEX IF NOT EXISTS idx_start_date ON activities(start_date);
        CREATE INDEX IF NOT EXISTS idx_start_date_local ON activities(start_date_local);

        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_type TEXT,
            activities_added INTEGER,
            activities_updated INTEGER,
            started_at TEXT,
            completed_at TEXT,
            status TEXT,
            error TEXT
        );
    """)
    conn.commit()
    conn.close()
    print("Database initialized.")


class StravaAuth:
    """Handle Strava OAuth authentication."""

    def __init__(self):
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
        self.client_id = config["strava"]["client_id"]
        self.client_secret = config["strava"]["client_secret"]
        self.access_token = None
        self.refresh_token = None
        self.expires_at = None

    def authenticate(self):
        """Get valid access token, refreshing if needed."""
        if os.path.exists(TOKENS_PATH):
            with open(TOKENS_PATH, "r") as f:
                tokens = json.load(f)
                self.access_token = tokens.get("access_token")
                self.refresh_token = tokens.get("refresh_token")
                self.expires_at = tokens.get("expires_at", 0)

            # Check if token is expired or about to expire (5 min buffer)
            if self.expires_at and time.time() < self.expires_at - 300:
                print("Using cached access token.")
                return self.access_token

            # Try to refresh
            if self.refresh_token:
                print("Refreshing access token...")
                if self._refresh_token():
                    return self.access_token

        # Need full OAuth flow
        print("Starting OAuth flow...")
        self._oauth_flow()
        return self.access_token

    def _refresh_token(self):
        """Refresh the access token."""
        response = requests.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
        )

        if response.status_code == 200:
            data = response.json()
            self._save_tokens(data)
            return True
        return False

    def _oauth_flow(self):
        """Run full OAuth flow."""
        auth_url = (
            f"https://www.strava.com/oauth/authorize?"
            f"client_id={self.client_id}&"
            f"redirect_uri=http://localhost:8000/authorized&"
            f"response_type=code&"
            f"scope=activity:read_all"
        )

        print(f"Opening browser for authorization...")
        print(f"If browser doesn't open, visit: {auth_url}")
        webbrowser.open(auth_url)

        # Capture the auth code
        auth_code = self._wait_for_callback()

        # Exchange for tokens
        response = requests.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": auth_code,
                "grant_type": "authorization_code",
            },
        )

        if response.status_code == 200:
            self._save_tokens(response.json())
        else:
            raise Exception(f"Token exchange failed: {response.text}")

    def _wait_for_callback(self):
        """Start local server to receive OAuth callback."""
        auth_code = None

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                nonlocal auth_code
                query = parse_qs(urlparse(self.path).query)
                auth_code = query.get("code", [None])[0]

                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h1>Success!</h1>"
                    b"<p>You can close this window.</p></body></html>"
                )

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("localhost", 8000), CallbackHandler)
        print("Waiting for authorization...")
        server.handle_request()

        if not auth_code:
            raise Exception("No authorization code received")
        return auth_code

    def _save_tokens(self, data):
        """Save tokens to file."""
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.expires_at = data["expires_at"]

        with open(TOKENS_PATH, "w") as f:
            json.dump(
                {
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                    "expires_at": self.expires_at,
                },
                f,
            )
        print("Tokens saved.")


class StravaSync:
    """Sync activities from Strava to SQLite."""

    BASE_URL = "https://www.strava.com/api/v3"

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {"Authorization": f"Bearer {access_token}"}

    def fetch_activities(self, per_page: int = 100, page: int = 1, after: int = None):
        """Fetch a page of activities."""
        params = {"per_page": per_page, "page": page}
        if after:
            params["after"] = after

        response = requests.get(
            f"{self.BASE_URL}/athlete/activities",
            headers=self.headers,
            params=params,
        )

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            # Rate limited - wait and retry
            print("Rate limited, waiting 60s...")
            time.sleep(60)
            return self.fetch_activities(per_page, page, after)
        else:
            raise Exception(f"API error {response.status_code}: {response.text}")

    def sync_all(self, force: bool = False):
        """Full sync of all activities."""
        conn = get_db_connection()

        # Check for existing activities
        existing = set()
        if not force:
            cursor = conn.execute("SELECT id FROM activities")
            existing = {row[0] for row in cursor.fetchall()}
            print(f"Found {len(existing)} existing activities in database.")

        # Log sync start
        sync_id = conn.execute(
            "INSERT INTO sync_log (sync_type, started_at, status) VALUES (?, ?, ?)",
            ("full" if force else "incremental", datetime.now().isoformat(), "running"),
        ).lastrowid
        conn.commit()

        added = 0
        updated = 0
        page = 1

        try:
            while True:
                print(f"Fetching page {page}...")
                activities = self.fetch_activities(per_page=100, page=page)

                if not activities:
                    break

                for activity in activities:
                    if activity["id"] in existing and not force:
                        continue

                    self._upsert_activity(conn, activity)
                    if activity["id"] in existing:
                        updated += 1
                    else:
                        added += 1
                        existing.add(activity["id"])

                conn.commit()
                print(f"  Processed {len(activities)} activities (added: {added}, updated: {updated})")

                if len(activities) < 100:
                    break

                page += 1
                time.sleep(0.5)  # Be nice to the API

            # Log success
            conn.execute(
                """UPDATE sync_log
                   SET activities_added=?, activities_updated=?, completed_at=?, status=?
                   WHERE id=?""",
                (added, updated, datetime.now().isoformat(), "success", sync_id),
            )
            conn.commit()

            print(f"\nSync complete: {added} added, {updated} updated")

        except Exception as e:
            conn.execute(
                "UPDATE sync_log SET completed_at=?, status=?, error=? WHERE id=?",
                (datetime.now().isoformat(), "error", str(e), sync_id),
            )
            conn.commit()
            raise

        finally:
            conn.close()

        return added, updated

    def _upsert_activity(self, conn, activity: dict):
        """Insert or update an activity."""
        conn.execute(
            """
            INSERT OR REPLACE INTO activities (
                id, name, type, sport_type, start_date, start_date_local, timezone,
                distance, moving_time, elapsed_time, total_elevation_gain,
                elev_high, elev_low, average_speed, max_speed,
                average_heartrate, max_heartrate, average_cadence,
                average_watts, weighted_average_watts, kilojoules,
                suffer_score, calories, achievement_count, kudos_count,
                comment_count, athlete_count, pr_count,
                start_latlng, end_latlng, summary_polyline,
                gear_id, device_name, raw_json, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                activity["id"],
                activity.get("name"),
                activity.get("type"),
                activity.get("sport_type"),
                activity.get("start_date"),
                activity.get("start_date_local"),
                activity.get("timezone"),
                activity.get("distance"),
                activity.get("moving_time"),
                activity.get("elapsed_time"),
                activity.get("total_elevation_gain"),
                activity.get("elev_high"),
                activity.get("elev_low"),
                activity.get("average_speed"),
                activity.get("max_speed"),
                activity.get("average_heartrate"),
                activity.get("max_heartrate"),
                activity.get("average_cadence"),
                activity.get("average_watts"),
                activity.get("weighted_average_watts"),
                activity.get("kilojoules"),
                activity.get("suffer_score"),
                activity.get("calories"),
                activity.get("achievement_count"),
                activity.get("kudos_count"),
                activity.get("comment_count"),
                activity.get("athlete_count"),
                activity.get("pr_count"),
                json.dumps(activity.get("start_latlng")),
                json.dumps(activity.get("end_latlng")),
                activity.get("map", {}).get("summary_polyline"),
                activity.get("gear_id"),
                activity.get("device_name"),
                json.dumps(activity),
                datetime.now().isoformat(),
            ),
        )


def main():
    """Run sync from command line."""
    import argparse

    parser = argparse.ArgumentParser(description="Sync Strava activities to SQLite")
    parser.add_argument("--force", action="store_true", help="Force full resync")
    parser.add_argument("--init", action="store_true", help="Initialize database only")
    args = parser.parse_args()

    init_db()

    if args.init:
        print("Database initialized. Run without --init to sync activities.")
        return

    auth = StravaAuth()
    access_token = auth.authenticate()

    sync = StravaSync(access_token)
    sync.sync_all(force=args.force)


if __name__ == "__main__":
    main()
