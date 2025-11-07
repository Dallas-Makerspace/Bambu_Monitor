import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional

@dataclass
class Notification:
    
    time: datetime = field(default_factory=datetime.utcnow)
    code: int = None
    id: Optional[str] = None
    body: Optional[str] = None
    color: str = field(default='green')
    expires_at: Optional[datetime] = None

    @classmethod
    def from_gmail(cls, msg_id: str, msg: dict, lifetime: float) -> "Notification":
        """Factory: build a Notification from Gmail message data."""
        headers = msg.get("payload", {}).get("headers", [])
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
        date_str = next((h["value"] for h in headers if h["name"] == "Date"), None)

        # parse or fallback
        if date_str:
            try:
                time_utc = parsedate_to_datetime(date_str)
            except Exception:
                time_utc = datetime.now(timezone.utc)
        else:
            time_utc = datetime.now(timezone.utc)

        snippet = msg.get("snippet", "(no snippet)")

        # 6-digit code extraction
        code = None
        m = re.search(r"\b\d{6}\b", snippet)
        if m:
            try:
                code = int(m.group())
            except ValueError:
                pass

        notif_id = msg_id or f"{time_utc.timestamp()}-{hash(subject)}"
        expires = time_utc + timedelta(seconds=lifetime)

        return cls(
            id=notif_id,
            time=time_utc,
            code=code,
            body=snippet,
            color='green',
            expires_at=expires,
        )

class FixedQueue:
    def __init__(self, max_size=5):
        self.max_size = max_size
        self.queue = []

    def push(self, notification):
        if not notification or not notification.id:
            return
        if any(n.id == notification.id for n in self.queue):
            return
        if len(self.queue) >= self.max_size:
            self.queue.pop(0)
        self.queue.append(notification)

    def pop(self, index=0):
        if self.queue:
            return self.queue.pop(index)
        return None

    def __len__(self):
        return len(self.queue)

    def __iter__(self):
        return iter(self.queue)