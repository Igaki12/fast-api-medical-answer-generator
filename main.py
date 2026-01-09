from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from fastapi import ( # pyright: ignore[reportMissingImports]
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse # pyright: ignore[reportMissingImports]

from app.auth import require_basic_auth
from app.models import DownloadStatusResponse, GenerateResponse
from app.services import file_manager
from app.services.legacy import pipeline as legacy_pipeline


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("medteria")

app = FastAPI(title="AI解説生成システム API", version="0.2.1")


@app.on_event("startup")
def startup() -> None:
    file_manager.ensure_base_dirs()


def _save_upload(job_id: str, upload: UploadFile) -> Path:
    input_dir = file_manager.ensure_job_input_dir(job_id)
    filename = Path(upload.filename).name
    destination = input_dir / filename
    with destination.open("wb") as handle:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    return destination


def _run_pipeline_job(
    job_id: str,
    input_path: Path,
    api_key: str | None,
    explanation_name: str,
    university: str,
    year: str,
    subject: str,
    author: str,
) -> None:
    try:
        legacy_pipeline.run_pipeline(
            job_id=job_id,
            input_path=input_path,
            api_key=api_key,
            explanation_name=explanation_name,
            university=university,
            year=year,
            subject=subject,
            author=author,
        )
    except Exception as exc:  # pragma: no cover - logged for runtime visibility
        logger.exception("Pipeline job failed: %s", job_id)
        file_manager.write_status(job_id, "failed", message=str(exc))


@app.post(
    "/api/v1/pipeline",
    response_model=GenerateResponse,
    status_code=202,
)
def pipeline_start(
    background_tasks: BackgroundTasks,
    input_file: UploadFile = File(...),
    api_key: str | None = Form(None),
    explanation_name: str = Form(...),
    university: str = Form(...),
    year: str = Form(...),
    subject: str = Form(...),
    author: str = Form(...),
    _auth: str = Depends(require_basic_auth),
) -> GenerateResponse:
    if not input_file.filename:
        raise HTTPException(status_code=400, detail="filename is required")

    job_id = f"pipeline-{uuid4()}"
    file_manager.write_status(job_id, "queued")
    input_path = _save_upload(job_id, input_file)
    background_tasks.add_task(
        _run_pipeline_job,
        job_id,
        input_path,
        api_key,
        explanation_name,
        university,
        year,
        subject,
        author,
    )
    return GenerateResponse(job_id=job_id, status="accepted")


@app.get(
    "/api/v1/pipeline/{job_id}",
    responses={202: {"model": DownloadStatusResponse}},
)
def pipeline_status(
    job_id: str,
    _auth: str = Depends(require_basic_auth),
):
    status = file_manager.read_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="job_id not found")

    if status["status"] not in {"done", "failed_to_convert"}:
        return JSONResponse(
            status_code=202,
            content=DownloadStatusResponse(
                job_id=job_id,
                status=status["status"],
                message=status.get("message"),
            ).model_dump(),
        )

    return JSONResponse(
        status_code=200,
        content=DownloadStatusResponse(
            job_id=job_id,
            status=status["status"],
            message=status.get("message"),
        ).model_dump(),
    )


@app.get(
    "/api/v1/pipeline/{job_id}/download",
    responses={202: {"model": DownloadStatusResponse}},
)
def pipeline_download(
    job_id: str,
    _auth: str = Depends(require_basic_auth),
):
    status = file_manager.read_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="job_id not found")

    if status["status"] not in {"done", "failed_to_convert"}:
        return JSONResponse(
            status_code=202,
            content=DownloadStatusResponse(
                job_id=job_id,
                status=status["status"],
                message=status.get("message"),
            ).model_dump(),
        )

    if status["status"] == "failed_to_convert":
        raise HTTPException(status_code=409, detail="PDF conversion failed for this job.")

    pdf_path = legacy_pipeline.prepare_download_pdf(job_id)
    metadata = file_manager.read_metadata(job_id) or {}
    filename = file_manager.build_pdf_filename(job_id, metadata.get("explanation_name"))
    return FileResponse(
        pdf_path,
        filename=filename,
        media_type="application/pdf",
    )
