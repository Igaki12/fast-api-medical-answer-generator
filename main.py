from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.auth import require_basic_auth
from app.models import DownloadStatusResponse, GenerateResponse
from app.services import file_manager, generator


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("medteria")

app = FastAPI(title="AI解説生成システム API", version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    file_manager.ensure_base_dirs()


def _save_upload(job_id: str, upload: UploadFile) -> Path:
    input_dir = file_manager.ensure_job_input_dir(job_id)
    destination = input_dir / upload.filename
    with destination.open("wb") as handle:
        handle.write(upload.file.read())
    return destination


def _run_job(job_id: str, input_path: Path) -> None:
    file_manager.write_status(job_id, "processing")
    try:
        output_dir = file_manager.ensure_job_output_dir(job_id)
        outputs = generator.generate_explanation(job_id, input_path, output_dir)
        zip_path = file_manager.create_zip(job_id, outputs)
        file_manager.write_status(job_id, "completed", extra={"zip_path": str(zip_path)})
    except Exception as exc:  # pragma: no cover - logged for runtime visibility
        logger.exception("Job failed: %s", job_id)
        file_manager.write_status(job_id, "failed", message=str(exc))


@app.post(
    "/api/v1/generate_explanation",
    response_model=GenerateResponse,
    status_code=202,
)
def generate_explanation(
    background_tasks: BackgroundTasks,
    upload: UploadFile = File(...),
    _auth: str = Depends(require_basic_auth),
) -> GenerateResponse:
    if not upload.filename:
        raise HTTPException(status_code=400, detail="filename is required")

    job_id = str(uuid4())
    file_manager.write_status(job_id, "accepted")
    input_path = _save_upload(job_id, upload)
    background_tasks.add_task(_run_job, job_id, input_path)
    return GenerateResponse(job_id=job_id, status="accepted")


@app.get(
    "/api/v1/download_explanation/{job_id}",
    responses={202: {"model": DownloadStatusResponse}},
)
def download_explanation(
    job_id: str,
    _auth: str = Depends(require_basic_auth),
):
    status = file_manager.read_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="job_id not found")

    if status["status"] != "completed":
        return JSONResponse(
            status_code=202,
            content=DownloadStatusResponse(
                job_id=job_id,
                status=status["status"],
                message=status.get("message"),
            ).model_dump(),
        )

    zip_path = file_manager.find_zip(job_id)
    if not zip_path:
        raise HTTPException(status_code=500, detail="zip file missing")
    return FileResponse(
        zip_path,
        filename=f"{job_id}.zip",
        media_type="application/zip",
    )
