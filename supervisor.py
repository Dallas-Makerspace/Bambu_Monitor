#!/usr/bin/env python3

"""
This script is called by .bashrc to initialize & supervise the Waydroid emulator, Android debugger, Bambu Handy app, and Python monitoring service.
"""

import subprocess
import threading
import time
import os

ANDROID_IP = "192.168.240.112"


def main():
    while True:
        try:
            # blocks indefinately
            startup()
        except KeyboardInterrupt:
            print("Interrupted — exiting.")
            break
        except Exception as e:
            print(f"Fatal error occurred: {e}")

        print("Restarting in 5 seconds...")
        os.system("pkill -f waydroid >/dev/null 2>&1")
        os.system("pkill -f main.py >/dev/null 2>&1")
        time.sleep(5)

def startup():
    process = subprocess.Popen(
        ["waydroid", "session", "start"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    stdout_thread = threading.Thread(target=read_output, args=(process.stdout, "STDOUT"))
    stderr_thread = threading.Thread(target=read_output, args=(process.stderr, "STDERR"))

    stdout_thread.start()
    stderr_thread.start()
    stdout_thread.join()
    stderr_thread.join()

    print(f"Process exited with code: {process.returncode}")

def read_output(pipe, prefix):
    for line in iter(pipe.readline, b''):
        decoded = line.decode().strip()
        print(f"{prefix}: {decoded}")
        # continue signal
        if 'Android with user 0 is ready' in decoded:
            connect_android_debugger()

def connect_android_debugger():
    print("Connecting")
    subprocess.run(["waydroid", "app", "launch", "bbl.intl.bambulab.com"])
    subprocess.run(["adb", "connect", ANDROID_IP])
    subprocess.run(
        ["handy_env/bin/python", "main.py"],
        env=os.environ.copy(),
        check=True
    )
    print("main.py exited — restarting soon")

if __name__ == "__main__":
    main()