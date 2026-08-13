"""Small atomic JSON persistence helper shared by local stores."""

import json
import os
from pathlib import Path
from typing import Any
import uuid


def write_json_atomic(path: str | Path, data: Any) -> None:
    """Write JSON through a sibling temporary file and atomically replace it."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
