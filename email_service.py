from datetime import datetime, timezone
import os
import json
import base64
import re
import threading
import time
from flask import Flask, request
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from email.utils import parsedate_to_datetime

from notification_store import FixedQueue, Notification

# === Configuration ===
PROJECT_ID = 'bambu-mfa-with-oauth'
TOPIC_ID = "gmail-push-test"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/cloud-platform"
]
PORT = 8080
LIFETIME = 300.0
WATCH_INTERVAL = 1.0

# === Globals ===
app = Flask(__name__)   # This API
gmail = None            # Gmail API
queue_out = None        # Shared queue with UI
notifier = None         # Notifications manager

def main(out_q=None):
    global notifier
    notifier = NotificationController(out_q)

    global gmail
    gmail = connect_oauth()
    register_watch(gmail)
    print(f"\n Flask server listening on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)


# === Pub/Sub Push Endpoint ===
@app.route("/pubsub/push", methods=["POST"])
def receive_push():
    envelope = request.get_json(silent=True)
    if not envelope or "message" not in envelope:
        print("Invalid push request")
        return ("Bad Request", 400)

    msg = envelope["message"]
    data = msg.get("data")

    if data:
        payload = base64.b64decode(data).decode("utf-8")
        print("\nReceived push payload:", payload)
        try:
            payload_json = json.loads(payload)
            history_id = payload_json.get("historyId")
            if history_id:
                fetch_latest_email_from_history(gmail, history_id)
        except Exception as e:
            print("Error processing payload:", e)
    else:
        print("\nReceived Pub/Sub message with no data")

    return ("", 200)


# === Gmail OAuth ===
def connect_oauth():
    """Authenticate user and return Gmail API client."""
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    service = build("gmail", "v1", credentials=creds)
    return service


# === Gmail Watch Setup ===
def register_watch(gmail):
    """Tell Gmail to publish inbox changes to the Pub/Sub topic."""
    topic = f"projects/{PROJECT_ID}/topics/{TOPIC_ID}"
    body = {"topicName": topic, "labelIds": ["INBOX"]}
    response = gmail.users().watch(userId="me", body=body).execute()
    print("Gmail watch registered:")
    print(json.dumps(response, indent=2))

def fetch_latest_email_from_history(gmail, new_history_id):
    last_history_id = load_last_history_id()

    start_id = last_history_id or new_history_id

    response = gmail.users().history().list(
        userId="me",
        startHistoryId=start_id,
        historyTypes=["messageAdded"]
    ).execute()

    records = response.get("history", [])
    if not records:
        print("No new messages in history.")
        save_last_history_id(new_history_id)
        return

    for record in records:
        for added in record.get("messagesAdded", []):
            msg_id = added["message"]["id"]
            msg = gmail.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

            # Skip sent or draft messages
            if any(lbl in msg.get("labelIds", []) for lbl in ["SENT", "DRAFT"]):
                continue

            addNotification(msg_id, msg)

    # Update baseline to latest known
    save_last_history_id(response.get("historyId", new_history_id))

def load_last_history_id():
    if os.path.exists("last_history_id.txt"):
        with open("last_history_id.txt") as f:
            return f.read().strip()
    return None

def save_last_history_id(history_id):
    with open("last_history_id.txt", "w") as f:
        f.write(str(history_id))


# === Notification Management ===
class NotificationController:
    def __init__(self, out_q):
        self.queue_out = out_q
        self.local_queue = FixedQueue()
        start_watcher(out_q, self.local_queue)

    def add_notification(self, notif):
        self.local_queue.push(notif)
        self.queue_out.put(list(self.local_queue.queue))

def addNotification(msg_id, msg):
    try:
        notif = Notification.from_gmail(msg_id, msg, LIFETIME)
        notifier.add_notification(notif)
        print(
            f"\nAdded Notification:\n"
            f"  Code: {notif.code}\n"
            f"  Time: {notif.time}\n"
            f"  Body: {notif.body[:80]}...\n"
        )
    except Exception as e:
        print("Error adding notification:", e)

def start_watcher(out_q, local_queue):
    """Background thread: update colors and expire notifications."""
    def watcher():
        while True:
            now = datetime.now(timezone.utc)
            changed = False
            for note in list(local_queue.queue):
                if not note.time or not note.expires_at:
                    continue
                total = (note.expires_at - note.time).total_seconds()
                elapsed = (now - note.time).total_seconds()
                ratio = elapsed / total

                if ratio >= 1.0:
                    local_queue.queue.remove(note)
                    changed = True
                    continue

                color = (
                    'green' if ratio < 1/3 else
                    'yellow' if ratio < 2/3 else
                    'red'
                )
                if note.color != color:
                    note.color = color
                    changed = True

            if changed:
                # send entire queue snapshot to UI
                out_q.put(list(local_queue.queue))

            time.sleep(WATCH_INTERVAL)

    threading.Thread(target=watcher, daemon=True).start()

if __name__ == "__main__":
    main()
