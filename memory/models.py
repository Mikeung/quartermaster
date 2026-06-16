import datetime
from dataclasses import dataclass, field


@dataclass
class ScanRecord:
    id: int | None
    scanner_name: str
    target: str
    result_json: str
    created_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    status: str = "completed"


@dataclass
class OperationalSnapshot:
    id: int | None
    snapshot_type: str
    data_json: str
    created_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    notes: str = ""
