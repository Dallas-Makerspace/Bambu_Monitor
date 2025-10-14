from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional
import json

@dataclass
class PrintJob:
    name: str
    status: str
    date: datetime
    duration: float
    machine: str
    weight: float
    materials: List[str]
    errors: List[str]

    def to_dict(self):
        d = asdict(self)
        # convert datetime to iso string for serialization
        d["date"] = self.date.isoformat()
        return d


class JobStore:
    def __init__(self):
        self.jobs: List[PrintJob] = []

    def add_job(self, job: PrintJob):
        self.jobs.append(job)

    def get_jobs(self, status: Optional[str] = None):
        if status:
            return [j for j in self.jobs if j.status.lower() == status.lower()]
        return list(self.jobs)

    def find_job(self, name: str, date: datetime):
        return next((j for j in self.jobs if j.name == name and j.date == date), None)
    
    def get_latest_job(self):
        if not self.jobs:
            return None
        return max(self.jobs, key=lambda j: j.date)

    def job_exists(self, name: str, date: datetime) -> bool:
        return any(
            job.name == name and job.date == date
            for job in self.jobs
        )

    def to_json(self, pretty: bool = True):
        if pretty:
            return json.dumps([j.to_dict() for j in self.jobs], indent=2)
        return json.dumps([j.to_dict() for j in self.jobs])

    def __len__(self):
        return len(self.jobs)

    def __repr__(self):
        return f"<JobStore jobs={len(self.jobs)}>"