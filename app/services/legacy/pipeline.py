from __future__ import annotations

from pathlib import Path

from app.services import file_manager
from app.services.legacy import convert_markdown, generate_markdown


def run_pipeline(
    job_id: str,
    input_path: Path,
    api_key: str | None,
    explanation_name: str,
    university: str,
    year: str,
    subject: str,
    author: str,
) -> Path:
    output_dir = file_manager.ensure_job_output_dir(job_id)
    markdown_dir = output_dir / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)

    file_manager.write_status(job_id, "generating_md")
    md_path = generate_markdown.generate_markdown_from_input(
        input_path=input_path,
        output_dir=markdown_dir,
        api_key=api_key,
        explanation_name=explanation_name,
        university=university,
        year=year,
        subject=subject,
        author=author,
    )
    file_manager.write_metadata(
        job_id,
        {
            "explanation_name": explanation_name,
            "university": university,
            "year": year,
            "subject": subject,
            "author": author,
            "created_at": file_manager.utcnow_iso(),
            "llm-model": generate_markdown.MODEL_NAME,
        },
    )
    file_manager.write_status(job_id, "done")
    return md_path


def prepare_download_zip(job_id: str) -> Path:
    output_dir = file_manager.ensure_job_output_dir(job_id)
    zip_path = file_manager.find_fresh_zip(job_id, max_age_days=7)
    if zip_path:
        return zip_path

    status = file_manager.read_status(job_id) or {}
    if status.get("status") == "failed_to_convert":
        zip_path = file_manager.create_pipeline_zip(job_id)
        return zip_path

    metadata = file_manager.read_metadata(job_id) or {}
    attribution_text = _build_attribution_text(
        metadata.get("university", ""),
        metadata.get("year", ""),
        metadata.get("subject", ""),
        metadata.get("author", ""),
    )
    md_paths = _collect_markdown_files(output_dir / "markdown")
    if not md_paths:
        raise RuntimeError("Markdown files are missing for this job.")

    try:
        for md_path in md_paths:
            convert_markdown.convert_markdown_to_pdf(
                md_path=md_path,
                output_dir=output_dir,
                attribution_text=attribution_text,
            )
    except Exception as exc:
        file_manager.write_status(job_id, "failed_to_convert", message=str(exc))
        _cleanup_conversion_artifacts(output_dir)
        zip_path = file_manager.create_pipeline_zip(job_id)
        return zip_path

    zip_path = file_manager.create_pipeline_zip(job_id)
    _cleanup_conversion_artifacts(output_dir)
    return zip_path


def _build_attribution_text(university: str, year: str, subject: str, author: str) -> str:
    parts = [
        (university or "").strip() or "不明",
        (year or "").strip() or "不明",
        (subject or "").strip() or "不明",
        (author or "").strip() or "不明",
    ]
    return " ".join(parts)


def _collect_markdown_files(markdown_dir: Path) -> list[Path]:
    if not markdown_dir.exists():
        return []
    return sorted(path for path in markdown_dir.rglob("*.md") if path.is_file())


def _cleanup_conversion_artifacts(output_dir: Path) -> None:
    import shutil

    for name in ("pdf", ".tmp", ".pandoc-tmp"):
        path = output_dir / name
        shutil.rmtree(path, ignore_errors=True)
