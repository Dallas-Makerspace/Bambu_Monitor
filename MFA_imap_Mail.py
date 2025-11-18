# MFA_imap_Mail.py
#   Uses IMAP Push to watch for email arrival and parse MFA PINs.
#   Updated with automatic color aging and expiry inside Idler.idle().

import imaplib2
import time
from threading import *
import email
import configparser
import ssl
import socket
import os
from html.parser import HTMLParser
import re
from datetime import datetime
from typing import List

import pytz

# Configurable delay and max timeout between reconnection attempts
RETRY_DELAY_SECONDS = 30
MAX_RETRIES = 20

# number of notifications shown
STACK_SIZE = 5
# minutes before a code expires
CODE_DURATION = 5


# ============================================================
# HTML Strip Utility
# ============================================================
class StripHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []

    def handle_data(self, data):
        self.result.append(data)

    def get_text(self):
        return ''.join(self.result)


def strip_html(text):
    remover = StripHTML()
    remover.feed(text)
    return remover.get_text()


# ============================================================
# Notification Object
# ============================================================
class Notification:
    id: str
    time: datetime
    code: int
    body: str
    color: str

    def __init__(self, id_=None, time_=None, code_=None, body_=None, color_="green"):
        self.id = id_
        self.time = time_
        self.code = code_
        self.body = body_
        self.color = color_


# ============================================================
# FixedStack for Notifications
# ============================================================
class FixedStack:
    stack: List[Notification]

    def __init__(self, stack):
        self.stack = []

    def push(self, data: Notification):
        self.stack.append(data)
        if len(self.stack) > STACK_SIZE:
            self.stack.reverse()
            self.stack.pop()
            self.stack.reverse()

    def remove(self, notification):
        return self.stack.remove(notification)


notificationStack = FixedStack([])


# ============================================================
# Idler (IMAP IDLE watcher)
# ============================================================
class Idler(object):
    def __init__(self, conn):
        self.thread = Thread(target=self.idle)
        self.M = conn
        self.event = Event()

    def start(self):
        self.thread.start()

    def stop(self):
        self.event.set()

    def join(self):
        self.thread.join()

    def idle(self):
        # Initial sync
        self.dosync_wrapper()

        # Loop forever
        while True:
            if self.event.is_set():
                return

            self.needsync = False

            def callback(args):
                if not self.event.is_set():
                    self.needsync = True
                    self.event.set()

            # Start idle
            self.M.idle(callback=callback)

            # Wait for server OR timer-wake
            self.event.wait()

            # Clear flag for next idle
            self.event.clear()

            # Perform sync if triggered
            if self.needsync:
                self.dosync_wrapper()

            # ====================================================
            # AGE NOTIFICATIONS & EXPIRE OLD ONES
            # Always runs, even without new emails
            # ====================================================
            now = datetime.now(pytz.timezone("US/Central"))
            to_remove = []

            for note in notificationStack.stack:
                mins_old = (now - note.time).total_seconds() / 60

                # Expire codes
                if mins_old >= CODE_DURATION:
                    to_remove.append(note)
                    continue

                # Color fractions
                fraction = mins_old / CODE_DURATION
                if fraction < 1/3:
                    note.color = "green"
                elif fraction < 2/3:
                    note.color = "yellow"
                else:
                    note.color = "blue"

            # Remove expired notifications
            for note in to_remove:
                try:
                    notificationStack.remove(note)
                except:
                    pass

    # ============================================================
    # Sync wrapper (handles disconnect)
    # ============================================================
    def dosync_wrapper(self):
        try:
            self.dosync2()
        except (imaplib2.IMAP4.abort, imaplib2.IMAP4.error, socket.error) as conn_error:
            print(f"Error occurred while fetching MFA code: {conn_error}")
            print("Attempting to reconnect...")
            try:
                new_conn = connect_imap()
                self.M = new_conn
                global M
                M = new_conn
                try:
                    self.dosync2()
                except Exception as e:
                    print("Secondary error during sync:", e)
            except Exception as e:
                print("Failed to reconnect:", e)

    # ============================================================
    # Primary email fetch/parser
    # ============================================================
    def dosync2(self):
        time.sleep(.2)
        resp_code, mails = M.search(None, 'FROM', '"Bambu Lab"')

        if len(mails[0]) > 0:
            dat = mails[0].decode().split()[-800:]
            mail_id = dat[-1]

            try:
                resp_code, mail_data = M.fetch(mail_id, '(RFC822)')
                message = email.message_from_bytes(mail_data[0][1]).as_string()
                message = " ".join(strip_html(message).split())
            except:
                time.sleep(1)
                return self.dosync2()

            try:
                body = re.search('Welcome to Bambu Lab([\\s\\S]*)Bambu Lab', message).group()
                codeStr = re.search("Your verification code is:\\s+\\d\\d\\d\\d\\d\\d", message).group()
                code = re.search("\\d\\d\\d\\d\\d\\d", codeStr).group()

                dateStr = re.search(
                    "Delivery-date: [A-Za-z]{3}, \\d{2} [A-Za-z]{3} \\d{4} \\d{2}:\\d{2}:\\d{2} -\\d{4}",
                    message
                ).group()

                date = re.search(
                    "\\d{2} [A-Za-z]{3} \\d{4} \\d{2}:\\d{2}:\\d{2} -\\d{4}",
                    dateStr
                ).group()

                t = time.strptime(date, "%d %b %Y %H:%M:%S %z")
                localized_time = datetime(*t[:6], tzinfo=pytz.FixedOffset(t.tm_gmtoff // 60))

                mins_old = (
                    datetime.now(pytz.timezone("US/Central")) - localized_time
                ).total_seconds() / 60

                if mins_old < CODE_DURATION:
                    # Assign initial color
                    fraction = mins_old / CODE_DURATION
                    if fraction < 1/3:
                        color = "green"
                    elif fraction < 2/3:
                        color = "yellow"
                    else:
                        color = "blue"

                    notificationStack.push(
                        Notification(
                            id_=mail_id,
                            time_=localized_time,
                            code_=code,
                            body_=body,
                            color_=color
                        )
                    )

            except:
                pass


# ============================================================
# IMAP Connection
# ============================================================
def connect_imap():
    global M
    for attempt in range(MAX_RETRIES):
        try:
            new_M = imaplib2.IMAP4_SSL(HOST)
            new_M.login(USERNAME, PASSWORD)
            new_M.select(source_folder)
            print("IMAP connection successful")
            M = new_M
            return new_M
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                raise


# ============================================================
# Notification Pump for UI Process
# ============================================================
def pump_notifications(out_q):
    while True:
        try:
            out_q.put(list(notificationStack.stack))
        except Exception as e:
            print("Pump error:", e)
        time.sleep(0.5)


# ============================================================
# Start IMAP Loop
# ============================================================
def start_imap_loop():
    global M, idler

    print("Connecting to email server...")
    M = connect_imap()
    idler = Idler(M)
    idler.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping IMAP loop...")
    finally:
        if idler:
            idler.stop()
            idler.join()
        if M:
            try: M.close()
            except: pass
            try: M.logout()
            except: pass


# ============================================================
# Config (does NOT start execution on import)
# ============================================================
config = configparser.ConfigParser()
config.read('MFA_Mail.cfg')

HOST = config['DEFAULT']['HOST']
USERNAME = config['DEFAULT']['USER']
PASSWORD = config['DEFAULT']['PASS']
source_folder = "INBOX"


if __name__ == "__main__":
    start_imap_loop()
