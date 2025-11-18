from datetime import datetime, timezone
import multiprocessing
import os
import threading
import time
from nicegui import ui

import MFA_imap_Mail  # SAFE TO IMPORT; DOESN'T AUTORUN

from gspread_updater import SheetClient


sheet_client = None
printer_data = None


@ui.page('/')
def index():

    shared_stack = index.shared_stack
    inbox_q = index.inbox_q

    index.printer_model = list(printer_data or [])

    # ----------------------------------------------------
    # PRINTER VIEW
    # ----------------------------------------------------
    @ui.refreshable
    def printers_view():
        ui.label('Printer Status')
        data, set_data = ui.state(index.printer_model)
        index.set_printers = set_data

        if not data:
            ui.label('No printers')
            return

        with ui.row().classes('w-full justify-around p-4'):
            for p in data:
                printer_name = p.get('printer', 'Unknown')
                status = p.get('status', 'Unknown')
                completion = p.get('completion', 'Unknown')
                remaining_hr = p.get('time_left', 'Unknown')

                label_text = remaining_hr if status == "Printing" else status

                color = 'primary'
                if status.lower() == 'success':
                    color = 'green'
                elif status.lower() == 'printing':
                    color = 'orange'

                with ui.column().classes('items-center'):
                    ui.label(printer_name).classes('text-lg font-semibold')
                    ui.circular_progress(
                        value=completion,
                        show_value=True,
                    ).props(f'color={color}')
                    ui.label(label_text).classes('text-sm text-gray-400')

    # ----------------------------------------------------
    # MFA NOTIFICATIONS VIEW
    # ----------------------------------------------------
    index.model = list(shared_stack)

    @ui.refreshable
    def notifications_view():
        ui.separator()
        ui.label('MFA Codes')

        data, set_data = ui.state(index.model)
        index.set_notifications = set_data

        if not data:
            ui.label("No notifications")
            return

        with ui.column().classes('w-full p-4'):
            for note in reversed(data):
                with ui.card().props('flat bordered').classes('p-2 m-1 w-full'):
                    with ui.row().classes('justify-between w-full'):
                        ui.label(f"Code: {note.code}")

                        # Convert timestamp to local time
                        local_time = note.time.astimezone().strftime("%I:%M %p").lstrip("0")

                        with ui.row():
                            ui.label("Time:")
                            ui.label(local_time).style(f"color:{note.color}")

                        ui.label(f"ID: {note.id}")


    # ----------------------------------------------------
    # QUEUE LISTENER
    # ----------------------------------------------------
    def queue_listener():
        # Wait until the page has rendered once and set_notifications exists
        while not hasattr(index, 'set_notifications'):
            time.sleep(0.1)

        while True:
            snapshot = inbox_q.get()
            try:
                index.set_notifications(snapshot)
            except Exception as e:
                print(f"[Queue Listener] Failed to update notifications: {e}")

    threading.Thread(target=queue_listener, daemon=True).start()

    # Initial paint
    printers_view()
    notifications_view()

    if printer_data:
        try:
            index.set_printers(list(printer_data))
        except Exception:
            pass


# --------------------------------------------------------
# MAIL PROCESS
# --------------------------------------------------------
def start_mail_process(out_q):
    """
    Runs MFA_imap_Mail's IMAP watcher and pumps notifications to the UI process.
    This runs in a separate process created by multiprocessing.
    """
    # Run IMAP watcher in a thread inside this process
    threading.Thread(target=MFA_imap_Mail.start_imap_loop, daemon=True).start()

    # Pump notifications (in this process's main thread)
    MFA_imap_Mail.pump_notifications(out_q)


# --------------------------------------------------------
# PRINTER POLLER
# --------------------------------------------------------
def poll_mfa_display():
    global printer_data
    while True:
        try:
            printer_data = sheet_client.get_mfa_display_info()
            print(f"[MFA Display] {len(printer_data)} entries")

            if hasattr(index, 'set_printers'):
                try:
                    index.set_printers(list(printer_data))
                except Exception as e:
                    print(f"[MFA Display Push Warning] {e}")

        except Exception as e:
            print(f"[MFA Display Error] {e}")

        time.sleep(60)


def start_background_thread():
    global sheet_client
    sheet_client = SheetClient("device_status")
    threading.Thread(target=poll_mfa_display, daemon=True).start()
    print("[MFA Display Thread] Started")


# --------------------------------------------------------
# MAIN ENTRY
# --------------------------------------------------------
def main():
    multiprocessing.freeze_support()
    ctx = multiprocessing.get_context("spawn")

    # We only really use this for the initial state; live updates come via inbox_q
    shared_stack = MFA_imap_Mail.notificationStack.stack
    inbox_q = ctx.Queue()

    index.shared_stack = shared_stack
    index.inbox_q = inbox_q

    print("[MFA] Starting mail subprocess...")
    mail_proc = ctx.Process(target=start_mail_process, args=(inbox_q,), daemon=True)
    mail_proc.start()

    start_background_thread()

    # Hide mouse cursor off-screen (your existing trick)
    os.system("sudo ydotool mousemove 9999 9999")

    print("[UI] Starting NiceGUI...")
    ui.run(dark=True, fullscreen=True, reload=False)


if __name__ == "__main__":
    main()
