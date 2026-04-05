import datetime
import os
import re
import subprocess
import time
import controller as cntrl
import parser as pr
import job_store as js
from gspread_updater import SheetClient


DEVICE_STATE_PATTERN = re.compile(r"^(?P<name>.+)\n(?P<state>Online|Busy|Offline|Idle)$")


def main():
    # Initialize
    store = js.JobStore()
    sheet_client = SheetClient("Raw Data")
    mfa_display_sheet = SheetClient("device_status")
    store.add_job(get_init_job(sheet_client))  

    while True:
        try:
            # wait for app to become responsive
            wait = 0
            while cntrl.tap_by_desc("Wait", whole_match=False):
                time.sleep(5)
                wait += 1
                if wait > 10:
                    subprocess.run(["sudo", "reboot"])

            # Check for new jobs since last run
            print("Checking for new jobs...")
            cntrl.go_to_printing_history()
            scroll_to_job(store.get_latest_job())
            check_for_later_jobs(store, sheet_client)

            # Update in-progress jobs in memory
            print("Updating in-progress jobs...")
            update_in_progress_jobs(store, sheet_client)

            # Update MFA display
            get_machine_statuses(mfa_display_sheet, sheet_client, store)

            # Purge very old jobs from in-memory store
            if len(store) > 100:
                store = store[50:]

            # Wait 30 seconds minutes before next check
            print("Waiting 30 seconds before next check")
            time.sleep(30)

        except Exception as e:
            print(f"Error occurred: {e}. Restarting loop...")
            log_error(e)
            cntrl.go_to_printing_history()
            continue


def update_in_progress_jobs(store, sheet_client):
    """
    Update all jobs in progress by checking their current status and errors, then sync to the sheet.
    """
    in_progress = [j for j in store.get_jobs() if j.status in ("Printing", "Printing paused")]
    for job in in_progress:
        if (datetime.datetime.now() - job.date).total_seconds() < 48 * 3600:
            print(f"Checking inprogress job {job.name}...")
            cntrl.go_to_printing_history()
            _job = scroll_to_job(job)
            job.status = _job.status
        # sometimes jobs in the handy list don't update
        # after 48 hours we will default to complete to avoid long periods of scrolling down the list
        else:
            job.status = "Success"

        sheet_client.update_job(job)
     
    cntrl.go_to_printing_history()

def scroll_to_job(job, prev_screen=None):
    """
    Scroll through the print history to locate a specific job by name and date, returning the job or None.
    """
    print(f"Scrolling down to locate job {job.name}...")
    screen = pr.parse_screen()
    snapshots = list(screen.keys())

    # Stop scrolling if the screen has not changed
    if prev_screen is not None and screen.keys() == prev_screen.keys():
        print(f"Job {job.name} not found.")
        return None

    for s in snapshots:
        try:
            _job = job_from_screen_entry(s)
        except ValueError:
            continue
        if _job.name == job.name and _job.date == job.date:
            return _job

    cntrl.scroll_down(screen)
    return scroll_to_job(job, screen)


def check_for_later_jobs(store, sheet_client):
    """
    Scan for newer jobs not yet in the store and add them, updating the sheet.
    """
    print(f"Checking for more recent jobs...")
    screen = pr.parse_screen()
    for s in screen.keys():
        try:
            j = job_from_screen_entry(s)
        except ValueError:
            continue
        if store.find_job(j.name, j.date) is None: 
            get_job_details(screen[s], j)
            store.add_job(j)
            sheet_client.update_job(j)

    # Scroll up and repeat as long as the screen keeps changing
    cntrl.scroll_up(screen)
    time.sleep(1)
    screen2 = pr.parse_screen()
    if screen2 != screen:
        check_for_later_jobs(store, sheet_client)


def get_job_details(bounds, job):
    """
    Tap into a job to extract weight and material details, then return to history.
    """
    print(f"Getting details for {job.name}...")
    cntrl.tap_by_bounds(bounds)

    content = list(pr.parse_screen(long_clickable_only=False).keys())
    try:
        index = content.index("Filaments")
    except ValueError:
        cntrl.tap_by_desc("Back")
        return job

    weight_str = content[index + 1] if index + 1 < len(content) else ""
    weight_val = re.sub(r"[^\d.]", "", weight_str)
    if weight_val:
        job.weight = float(weight_val)

    # After the weight, the screen lists materials (optionally grouped by nozzle) with AMS slots interspersed.
    # Collect only the material entries (contain "| <number>g") and ignore nozzle headers and AMS slot labels.
    material_pattern = re.compile(r".+\|\s*\d+(\.\d+)?g", re.IGNORECASE)
    for entry in content[index + 2 :]:
        lower_entry = entry.lower()
        if lower_entry.startswith("print again"):
            break
        if "nozzle" in lower_entry:
            continue
        if material_pattern.fullmatch(entry.strip()):
            job.materials.append(entry.strip())
        
    cntrl.tap_by_desc("Back")
    return job


def job_from_screen_entry(s):
    """
    Convert a parsed screen entry list into a PrintJob object.
    """
    if s is None:
        return None 
    
    s = [entry.strip() for entry in list(s) if entry and entry.strip()]
    if len(s) < 5:
        raise ValueError(f"Unexpected history entry format: {s}")

    # Structure is typically:
    # [type, status, name, (<optional extra line(s)>), (<optional duration>), machine, plate+date]
    # Duration may be absent (e.g., some canceled jobs), so detect it by pattern.
    _duration = 0.0
    for token in s[3:-2]:
        parsed = _parse_duration_hours(token)
        if parsed is not None:
            _duration = round(parsed, 1)
            break

    return js.PrintJob(
        status = s[1],
        name = s[2],
        duration = _duration,
        machine = s[-2],
        date = pr.parse_job_date(s[-1]),
        weight=0.0,
        materials=[],
        errors=""
    )

def _parse_duration_hours(token):
    """
    Parse a duration token (e.g. "8.2h", "3min", "45s") into hours.
    Returns None when the token is not a duration.
    """
    raw = token.strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(s|min|h)", raw)
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2)
    if unit == "s":
        return value / 3600
    if unit == "min":
        return value / 60
    return value


def get_init_job(sheet_client):
    """
    Return the job to resume on startup: earliest in-progress, most recent in sheets, or first GUI entry.
    """
    
    # Earliest row that still needs updating
    latest_job = sheet_client.get_oldest_in_progress_job()

    # If no rows in progress, resume from latest row in sheet
    if latest_job is None:
        latest_job = sheet_client.get_most_recent_job()

        # Fallback to GUI if no jobs recorded at all
        # This becomes the first entry.
        if latest_job is None:
            latest_job = get_first_gui_entry()
            sheet_client.update_job(latest_job)

    return latest_job


def get_first_gui_entry():
    """
    Return the first job entry visible in the GUI.
    """
    cntrl.go_to_printing_history()
    screen = pr.parse_screen()
    snapshot = list(screen.keys())[0]
    job = job_from_screen_entry(snapshot)
    get_job_details(screen[snapshot], job)
    return job


def get_machine_statuses(mfa_display_sheet, job_sheet, store):
    printer_rows = mfa_display_sheet.get_printer_config(max_rows=32)
    overview_states = get_device_overview_states()

    for row_number, printer in printer_rows:
        cntrl.go_to_device_page(printer)
        record_warning_for_machine(store, job_sheet, printer)
        screen = pr.parse_screen(long_clickable_only=False)
        time_left_str = next((x for x in screen.keys() if re.fullmatch(r'-.*m', x)), None)

        if time_left_str is None:
            status = overview_states.get(printer, "Idle")
            if status == "Busy":
                status = "Printing"
            if next((x for x in screen.keys() if re.fullmatch(r'Success', x)), None):
                status = "Success"
            completion = 1 if status in ("Success", "Idle") else 0
            time_left = 0
        else:
            status = "Printing"
            completion_str = next((x for x in screen.keys() if re.fullmatch(r'\d{1,2}%', x)), "100")
            completion = float(completion_str.replace('%', '')) / 100
            time_left = time_left_str

        row_data = {"Status": status, "Completion": completion, "Time": time_left}
        mfa_display_sheet.set_mfa_display_info(row_number, row_data)


def get_device_overview_states():
    """
    Read the device list page once and map printer names to their summarized state.
    """
    overview = {}
    os.system("adb shell input keyevent KEYCODE_BACK")
    cntrl.tap_by_desc("Devices")
    screen = pr.parse_screen(long_clickable_only=False)

    for entry in screen.keys():
        match = DEVICE_STATE_PATTERN.fullmatch(entry)
        if not match:
            continue
        overview[match.group("name")] = match.group("state")

    return overview

def get_active_job_for_machine(store, machine):
    """
    Return the most recent in-progress job for a specific machine, if any.
    """
    active_jobs = [j for j in store.get_jobs(status="Printing") if j.machine == machine]
    if not active_jobs:
        return None
    return max(active_jobs, key=lambda j: j.date)


def record_warning_for_machine(store, job_sheet, machine):
    """
    If a warning popup is present on the device page, record it against the active job and dismiss it.
    """
    if not cntrl.find_by_desc("Warning"):
        return

    content = list(pr.parse_screen(long_clickable_only=False).keys())
    error_message = content[1] if len(content) > 1 else None

    active_job = get_active_job_for_machine(store, machine)
    if active_job and error_message and error_message not in active_job.errors:
        active_job.errors += error_message if not active_job.errors else f" {error_message}"
        job_sheet.update_job(active_job)

    # Clear the popup so status parsing is not disrupted
    os.system("adb shell input keyevent KEYCODE_BACK")


def log_error(e):
    ts = datetime.datetime.now().strftime("[%Y-%m-%d_%H-%M-%S]")
    base_dir = "monitoring_errors"
    os.makedirs(base_dir, exist_ok=True)

    err_dir = os.path.join(base_dir, f"err_{ts}")
    os.makedirs(err_dir, exist_ok=True)

    # Error text
    with open(os.path.join(err_dir, "error.txt"), "w") as f:
        f.write(f"Error occurred at {ts}:\n{str(e)}\n")

    # XML View
    os.system("adb shell uiautomator dump /sdcard/view.xml")
    os.system(f"adb pull /sdcard/view.xml {err_dir}/view.xml > /dev/null")

    # Screenshot
    screenshot_path = os.path.join(err_dir, "screenshot.png")
    with open(screenshot_path, "wb") as f:
        subprocess.run(["adb", "exec-out", "screencap", "-p"], stdout=f)

    print(f"Error logged in {err_dir}. Restarting loop...")


if __name__ == "__main__":
    main()
