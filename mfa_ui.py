import multiprocessing
from multiprocessing import context
import threading
from nicegui import ui
import email_service
from notification_store import FixedQueue


def start_mail_process(ctx, out_q):
    email_service.main(out_q)


@ui.page('/')  # UI lives here
def index():
    shared_stack = index.shared_stack
    inbox_q = index.inbox_q

    ui.label('Notification Viewer')

    index.model = list(shared_stack)

    @ui.refreshable
    def notifications_view():
        # bind NiceGUI state to the current model
        data, set_data = ui.state(index.model)
        # expose the state setter so the controller can update reactively
        index.set_notifications = set_data
        # render from reactive state (data)
        if not data:
            ui.label('No notifications')
            return
        with ui.column().classes('w-full p-4'):
            for note in reversed(data):
                with ui.card().props('flat bordered').classes('p-2 m-1 w-full'):
                    with ui.row().classes('justify-between w-full'):
                        ui.label(f"Code: {note.code}")
                        ui.label(f"Time: {note.time}")
                        ui.label(f"ID: {note.id}")

    def queue_listener():
        """Receives full queue snapshots from MFA2 and updates state reactively."""
        while True:
            snapshot = inbox_q.get()
            index.set_notifications(snapshot)

    threading.Thread(target=queue_listener, daemon=True).start()

    # initial paint
    notifications_view()


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

    ui.run(dark=True, fullscreen=True, reload=False)


if __name__ == "__main__":
    main()
