from dataclasses import dataclass, field
from typing import Optional, Dict
@dataclass
class Event:
    title: str
    url: str
    date: str = field(default="")
    time: str = field(default="")

@dataclass
class Account:
    id: str
    password: str
    row_num: int
    type: str = field(default="general")
    participant: str = field(default="")
    action: str = field(default="")
    ss_event_date: Optional[str] = field(default=None)
    ss_event_store: Optional[str] = field(default=None)
    
@dataclass
class ScrapeResult:
    status: str  # e.g., 'available', 'scheduled', 'error'
    data: Optional[Dict] = field(default=None)
    message: Optional[str] = field(default=None)