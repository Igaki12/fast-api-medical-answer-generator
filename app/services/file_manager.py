from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
INPUTS_DIR = DATA_DIR / "inputs"
OUTPUTS_DIR = DATA_DIR / "outputs"


def ensure_base_dirs() -> None:
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_job_input_dir(job_id: str) -> Path:
    path = INPUTS_DIR / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_job_output_dir(job_id: str) -> Path:
    path = OUTPUTS_DIR / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_status(job_id: str, status: str, message: str | None = None, extra: dict | None = None) -> None:
    payload = {
        "job_id": job_id,
        "status": status,
        "message": message,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)
    status_path = ensure_job_output_dir(job_id) / "status.json"
    status_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def read_status(job_id: str) -> Optional[dict]:
    status_path = OUTPUTS_DIR / job_id / "status.json"
    if not status_path.exists():
        return None
    return json.loads(status_path.read_text(encoding="utf-8"))


def create_zip(job_id: str, outputs: Iterable[Path]) -> Path:
    import zipfile

    output_dir = ensure_job_output_dir(job_id)
    zip_path = output_dir / f"{job_id}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in outputs:
            archive.write(path, arcname=path.name)
    return zip_path


def find_zip(job_id: str) -> Optional[Path]:
    zip_path = OUTPUTS_DIR / job_id / f"{job_id}.zip"
    if zip_path.exists():
        return zip_path
    return None
