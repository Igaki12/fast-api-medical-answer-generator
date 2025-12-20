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
from app.services import file_manager, generator
from app.services.legacy import pipeline as legacy_pipeline


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("medteria")

app = FastAPI(title="AI解説生成システム API", version="0.2.0")


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


def _run_legacy_job(
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
        logger.exception("Legacy job failed: %s", job_id)
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


@app.post(
    "/api/v1/legacy/pipeline",
    response_model=GenerateResponse,
    status_code=202,
)
def legacy_pipeline_start(
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

    job_id = f"legacy-{uuid4()}"
    file_manager.write_status(job_id, "queued")
    input_path = _save_upload(job_id, input_file)
    background_tasks.add_task(
        _run_legacy_job,
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
    "/api/v1/legacy/pipeline/{job_id}",
    responses={202: {"model": DownloadStatusResponse}},
)
def legacy_pipeline_status(
    job_id: str,
    _auth: str = Depends(require_basic_auth),
):
    status = file_manager.read_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="job_id not found")

    if status["status"] != "done":
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
    "/api/v1/legacy/pipeline/{job_id}/download",
    responses={202: {"model": DownloadStatusResponse}},
)
def legacy_pipeline_download(
    job_id: str,
    _auth: str = Depends(require_basic_auth),
):
    status = file_manager.read_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="job_id not found")

    if status["status"] != "done":
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
