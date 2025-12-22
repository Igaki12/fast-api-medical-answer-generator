from __future__ import annotations

import json
from datetime import datetime, timezone
import time
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


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_status(job_id: str, status: str, message: str | None = None, extra: dict | None = None) -> None:
    payload = {
        "job_id": job_id,
        "status": status,
        "message": message,
        "updated_at": utcnow_iso(),
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


def write_metadata(job_id: str, metadata: dict) -> Path:
    metadata_path = ensure_job_output_dir(job_id) / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=True, indent=2), encoding="utf-8")
    return metadata_path


def read_metadata(job_id: str) -> Optional[dict]:
    metadata_path = OUTPUTS_DIR / job_id / "metadata.json"
    if not metadata_path.exists():
        return None
    return json.loads(metadata_path.read_text(encoding="utf-8"))


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


def find_fresh_zip(job_id: str, max_age_days: int) -> Optional[Path]:
    zip_path = find_zip(job_id)
    if not zip_path:
        return None
    age_seconds = time.time() - zip_path.stat().st_mtime
    if age_seconds <= max_age_days * 86400:
        return zip_path
    try:
        zip_path.unlink()
    except Exception:
        pass
    return None


def create_pipeline_zip(job_id: str) -> Path:
    import zipfile

    output_dir = ensure_job_output_dir(job_id)
    zip_path = output_dir / f"{job_id}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        status_path = output_dir / "status.json"
        if status_path.exists():
            archive.write(status_path, arcname="status.json")

        metadata_path = output_dir / "metadata.json"
        if metadata_path.exists():
            archive.write(metadata_path, arcname="metadata.json")

        for folder in ("markdown", "pdf"):
            folder_path = output_dir / folder
            if not folder_path.exists():
                continue
            for path in folder_path.rglob("*"):
                if path.is_file():
                    arcname = f"{folder}/{path.relative_to(folder_path)}"
                    archive.write(path, arcname=arcname)
    return zip_path


def create_legacy_zip(job_id: str) -> Path:
    return create_pipeline_zip(job_id)
