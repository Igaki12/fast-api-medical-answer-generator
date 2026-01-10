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
    file_manager.write_status(job_id, "generating_pdf")
    attribution_text = _build_attribution_text(university, year, subject, author)
    pdf_path = _convert_latest_markdown_to_pdf(
        job_id=job_id,
        output_dir=output_dir,
        attribution_text=attribution_text,
    )
    file_manager.cache_job_pdf(job_id, file_manager.build_pdf_filename(job_id, explanation_name), pdf_path)
    _cleanup_conversion_artifacts(output_dir, keep_pdf=False)
    file_manager.write_status(job_id, "done")
    return md_path


def prepare_download_pdf(job_id: str) -> Path:
    output_dir = file_manager.ensure_job_output_dir(job_id)
    status = file_manager.read_status(job_id) or {}
    if status.get("status") == "failed_to_convert":
        raise RuntimeError("PDF conversion previously failed for this job.")

    metadata = file_manager.read_metadata(job_id) or {}
    filename = file_manager.build_pdf_filename(job_id, metadata.get("explanation_name"))
    pdf_path = file_manager.find_pdf(job_id, filename)
    if not pdf_path:
        raise RuntimeError("PDF file is missing for this job.")
    return pdf_path


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


def _select_latest_markdown(md_paths: list[Path]) -> Path:
    return max(md_paths, key=lambda path: (path.stat().st_mtime, path.name))


def _convert_latest_markdown_to_pdf(
    job_id: str,
    output_dir: Path,
    attribution_text: str,
) -> Path:
    md_paths = _collect_markdown_files(output_dir / "markdown")
    if not md_paths:
        raise RuntimeError("Markdown files are missing for this job.")
    target_md = _select_latest_markdown(md_paths)
    try:
        return convert_markdown.convert_markdown_to_pdf(
            md_path=target_md,
            output_dir=output_dir,
            attribution_text=attribution_text,
        )
    except Exception as exc:
        file_manager.write_status(job_id, "failed_to_convert", message=str(exc))
        _cleanup_conversion_artifacts(output_dir, keep_pdf=False)
        raise

def _cleanup_conversion_artifacts(output_dir: Path, keep_pdf: bool) -> None:
    import shutil

    names = [".tmp", ".pandoc-tmp"]
    if not keep_pdf:
        names.append("pdf")
    for name in names:
        path = output_dir / name
        shutil.rmtree(path, ignore_errors=True)
