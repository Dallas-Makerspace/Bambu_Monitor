#!/usr/bin/env python3
"""
Supervisor for Waydroid, Android debugger, main app logic, and the NiceGUI UI.
Ensures processes start in order, are monitored, and restarted on crash.
"""

import re
import subprocess
import threading
import time
import os
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from google import pubsub_v1

ANDROID_IP = "192.168.240.112"
MFA_UI = "mfa_ui.py"
MONITORING_SERVICE = "bambu_monitor.py"
PYTHON_ENV = "handy_env/bin/python"
UI_URL = "http://127.0.0.1:8080"

def main():
    while True:
        try:
            schedule_daily_restart()
            startup()
        except KeyboardInterrupt:
            print("Interrupted — shutting down.")
            cleanup()
            break
        except Exception as e:
            print(f"Fatal error occurred: {e}")

        print("Restarting all in 5 seconds...")
        cleanup()
        time.sleep(5)

def startup():
    print("[Supervisor] Starting Waydroid session...")
    waydroid_proc = subprocess.Popen(
        ["waydroid", "session", "start"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout_thread = threading.Thread(target=read_output, args=(waydroid_proc.stdout, "STDOUT"))
    stderr_thread = threading.Thread(target=read_output, args=(waydroid_proc.stderr, "STDERR"))
    stdout_thread.start()
    stderr_thread.start()
    stdout_thread.join()
    stderr_thread.join()

    print(f"[Supervisor] Waydroid exited with code {waydroid_proc.returncode}")

def read_output(pipe, prefix):
    for line in iter(pipe.readline, ""):
        print(f"{prefix}: {line.strip()}")
        if "Android with user 0 is ready" in line:
            on_ready()

def on_ready():
    bambu_monitor_startup()
    cloudflared_startup()
    mfa_mail_startup()

def bambu_monitor_startup():
    """Starts the Android app, launches backend logic, and opens the UI."""
    print("[Supervisor] Connecting Android debugger and launching app...")
    subprocess.run(["waydroid", "app", "launch", "bbl.intl.bambulab.com"])
    subprocess.run(["adb", "connect", ANDROID_IP])

    print("[Supervisor] Launching print monitoring service (bambu_monitor.py)...")
    main_proc = subprocess.Popen(
        [PYTHON_ENV, MONITORING_SERVICE],
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    threading.Thread(target=log_stream, args=(main_proc, "bambu_monitor.out", "MAIN"), daemon=True).start()

def mfa_mail_startup(): 
    print("[Supervisor] Launching UI service...")
    ui_proc = subprocess.Popen(
        [PYTHON_ENV, MFA_UI],
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    threading.Thread(target=log_stream, args=(ui_proc, "mfa_ui.out", "UI"), daemon=True).start()


def cloudflared_startup():
    """Start a Cloudflare quick tunnel and update the Pub/Sub push endpoint."""
    print("[Supervisor] Starting Cloudflare quick tunnel...")

    # Read Cloudflare token from file
    try:
        with open("cf_token.txt", "r") as f:
            token = f.read().strip()
    except Exception as e:
        print(f"[Supervisor] Failed to read cf_token.txt: {e}")
        return

    tunnel_proc = subprocess.Popen(
        ["cloudflared", "tunnel", "run", "--token", token],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def log_stream(proc, filename, tag):
    """Mirror process stdout to a file with timestamps."""
    with open(filename, "a", buffering=1) as f:  # line-buffered append mode
        for line in proc.stdout:
            ts = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
            formatted = f"{ts} [{tag}] {line}"
            print(formatted, end="")   # keep live console output
            f.write(formatted)

def cleanup():
    """Terminate any running child processes."""
    print("[Supervisor] Cleaning up old processes...")
    os.system("pkill -f waydroid >/dev/null 2>&1")
    os.system("pkill -f adb >/dev/null 2>&1")
    os.system(f"pkill -f {MFA_UI} >/dev/null 2>&1")
    os.system(f"pkill -f {MONITORING_SERVICE} >/dev/null 2>&1")

def schedule_daily_restart():
    """Run `sudo restart` nightly at local midnight."""
    tz = ZoneInfo("America/Chicago") if ZoneInfo else None

    def loop():
        while True:
            sleep_s = _seconds_until_next_midnight(tz)
            print(f"[Supervisor] Next scheduled restart in ~{sleep_s} seconds (midnight local).")
            time.sleep(sleep_s)
            os.system("sudo restart")

    threading.Thread(target=loop, daemon=True).start()

def _seconds_until_next_midnight(tzinfo=None) -> int:
    now = datetime.now(tzinfo) if tzinfo else datetime.now()
    tomorrow = (now + timedelta(days=1)).date()
    next_midnight = datetime.combine(tomorrow, dtime(0, 0, 0), tzinfo)
    return max(1, int((next_midnight - now).total_seconds()))


if __name__ == "__main__":
    main()
