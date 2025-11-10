from datetime import datetime, timezone
import math
import multiprocessing
from multiprocessing import context
import os
import threading
import time
from nicegui import ui
import email_service
from gspread_updater import SheetClient
from notification_store import FixedQueue

sheet_client = None
printer_data = None  # global latest snapshot from the poller

@ui.page('/')  # UI lives here
def index():

    shared_stack = index.shared_stack
    inbox_q = index.inbox_q

    index.printer_model = list(printer_data or [])

    @ui.refreshable
    def printers_view():
        ui.label('Printer Status')
        """Top row with a column per printer; updates via index.set_printers(...)"""
        data, set_data = ui.state(index.printer_model)
        index.set_printers = set_data  # expose setter for background thread

        if not data:
            ui.label('No printers')
            return

        with ui.row().classes('w-full justify-around p-4'):
            for p in data:
                print(p)
                printer_name = p.get('printer', 'Unknown')
                status = p.get('status', 'Unknown')
                completion = p.get('completion', 'Unknown')
                remaining_hr = p.get('time_left', 'Unknown')
                label_text = status
                if status == "Printing":
                    label_text = remaining_hr

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

    


    index.model = list(shared_stack)

    @ui.refreshable
    def notifications_view():
        ui.separator()
        ui.label('MFA Codes')
        data, set_data = ui.state(index.model)
        index.set_notifications = set_data

        if not data:
            ui.label('No notifications')
            return
        with ui.column().classes('w-full p-4'):
            for note in reversed(data):
                with ui.card().props('flat bordered').classes('p-2 m-1 w-full'):
                    with ui.row().classes('justify-between w-full'):
                        ui.label(f"Code: {note.code}")
                        with ui.row():
                            ui.label("Time:")
                            local_time = note.time.replace(tzinfo=timezone.utc).astimezone().strftime("%I:%M %p").lstrip("0")
                            ui.label(local_time).style(f"color:{note.color}")
                        ui.label(f"ID: {note.id}")

    def queue_listener():
        """Receives full queue snapshots from MFA2 and updates state reactively."""
        while True:
            snapshot = inbox_q.get()
            index.set_notifications(snapshot)

    threading.Thread(target=queue_listener, daemon=True).start()

    # ----- INITIAL PAINT -----
    printers_view()
    notifications_view()

    if printer_data:
        try:
            index.set_printers(list(printer_data))
        except Exception:
            pass

def start_mail_process(ctx, out_q):
    email_service.main(out_q)

def poll_mfa_display():
    """Background poller: refreshes global printer_data and pushes to UI if available."""
    global printer_data
    while True:
        try:
            printer_data = sheet_client.get_mfa_display_info()
            print(f"[MFA Display Update] Retrieved {len(printer_data)} entries")

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
    thread = threading.Thread(target=poll_mfa_display, daemon=True)
    thread.start()
    print("[MFA Display Thread] Started")


def main():
    multiprocessing.freeze_support()
    ctx = multiprocessing.get_context("spawn")

    shared_stack = FixedQueue()
    inbox_q = ctx.Queue()

    # attach to page so it can see them
    index.shared_stack = shared_stack
    index.inbox_q = inbox_q

    print("starting mail...")
    mail_proc = ctx.Process(target=start_mail_process, args=(ctx, inbox_q), daemon=True)
    mail_proc.start()

    start_background_thread()
    os.system("sudo ydotool mousemove 9999 9999")
    ui.run(dark=True, fullscreen=True, reload=False)


if __name__ == "__main__":
    main()
