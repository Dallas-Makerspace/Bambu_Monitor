from typing import List, Optional
import gspread
from datetime import datetime

from job_store import PrintJob

CREDENTIALS_PATH = 'printer-monitoring-474822-bdfc6f0da109.json'
SPREADSHEET_NAME = "print-records"
WORKSHEET_NAME = "Raw Data"

class SheetClient:
    def __init__(self):
        self.credentials_path = CREDENTIALS_PATH
        self.spreadsheet_name = SPREADSHEET_NAME
        self.worksheet_name = WORKSHEET_NAME
        self._client = None
        self._spreadsheet = None
        self._sheet = None

    def _connect(self):
        """Lazy initialization of gspread client and worksheet."""
        if self._client is None:
            self._client = gspread.service_account(filename=self.credentials_path)
        if self._spreadsheet is None:
            self._spreadsheet = self._client.open(self.spreadsheet_name)
        if self._sheet is None:
            self._sheet = self._spreadsheet.worksheet(self.worksheet_name)
        return self._sheet

    def find_job_row(self, name: str, date: datetime):
        """
        Checks the sheet for a job with the given name and date.
        If found, returns the row number and row.
        If not found, returns the next available empty row number.
        """
        ws = self._connect()
        all_values = ws.get_all_values()

        for i, row in enumerate(all_values, start=1):
            if len(row) < 3:
                continue

            row_name = row[0].strip()
            row_date_str = row[2].strip()

            try:
                row_date = datetime.strptime(row_date_str, "%m/%d/%Y %H:%M")
            except Exception:
                continue

            if row_name == name and row_date == date:
                return i, row

        return len(all_values) + 1, ""

    def update_job(self, job):
        """
        Finds the row for the given job by name and date.
        Overwrites that row’s data, or writes it to the next empty row if not found.
        """
        ws = self._connect()
        i, row = self.find_job_row(job.name, job.date)
        values = self.map_job_to_row(job, row)
        ws.update(f"A{i}:H{i}", [values])

    def map_job_to_row(self, job, row = None):
        """
        Maps PrintJob object to literals for data entry
        """
        errors = row[7] if row and len(row) > 7 else ""
        errors += (" " + job.errors) if job.errors not in errors else ""
        values = [
            job.name,
            job.status,
            job.date.strftime("%m/%d/%Y %H:%M"),
            job.duration,
            job.machine,
            job.weight,
            ", ".join(job.materials),
            errors
        ]
        return values

    def get_oldest_in_progress_job(self) -> Optional[PrintJob]:
        """
        Returns the oldest PrintJob that is still in progress (status = 'Printing').
        """
        ws = self._connect()
        rows = ws.get_all_values()

        if not rows:
            return None

        # Convert and filter
        jobs = [
            self.row_to_printjob(r)
            for r in rows
            if len(r) >= 2 and r[1].strip().lower() == "printing"
        ]

        if not jobs:
            return None

        return min(jobs, key=lambda j: j.date)


    def get_most_recent_job(self) -> Optional[PrintJob]:
        """
        Returns the most recent PrintJob based on the date column.
        """
        ws = self._connect()
        rows = ws.get_all_values()

        if not rows:
            return None

        jobs = [self.row_to_printjob(r) for r in rows if len(r) >= 3 and r[2].strip()]

        if not jobs:
            return None

        return max(jobs, key=lambda j: j.date)

    def row_to_printjob(self, row: List[str]) -> PrintJob:
        """
        Convert a Google Sheet row into a PrintJob instance.
        name, status, date, duration, machine, weight, materials, errors
        """
        return PrintJob(
            name=row[0],
            status=row[1],
            date=datetime.strptime(row[2], "%m/%d/%Y %H:%M"),
            duration=float(row[3]) if row[3] else 0.0,
            machine=row[4],
            weight=float(row[5]) if row[5] else 0.0,
            materials=[m.strip() for m in row[6].split(",")] if row[6] else [],
            errors= row[7] if len(row) > 7 else ""
        )