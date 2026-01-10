from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


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


def build_pdf_filename(job_id: str, explanation_name: str | None) -> str:
    import re

    base = (explanation_name or "").strip() or job_id
    safe = base.replace("/", "_").replace("\\", "_")
    safe = re.sub(r'[<>:"|?*\x00-\x1f]', "_", safe)
    safe = re.sub(r"\s+", " ", safe).strip(" .")
    if not safe:
        safe = job_id
    if not safe.lower().endswith(".pdf"):
        safe = f"{safe}.pdf"
    return safe


def find_pdf(job_id: str, filename: str) -> Optional[Path]:
    pdf_path = OUTPUTS_DIR / job_id / filename
    if pdf_path.exists():
        return pdf_path
    return None


def cache_job_pdf(job_id: str, filename: str, pdf_path: Path) -> Path:
    import shutil

    output_dir = ensure_job_output_dir(job_id)
    cached_path = output_dir / filename
    shutil.copyfile(pdf_path, cached_path)
    return cached_path
