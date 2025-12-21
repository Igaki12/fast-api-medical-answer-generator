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

    file_manager.write_status(job_id, "converting")
    attribution_text = _build_attribution_text(university, year, subject, author)
    convert_markdown.convert_markdown_to_pdf(
        md_path=md_path,
        output_dir=output_dir,
        attribution_text=attribution_text,
    )

    file_manager.write_status(job_id, "done")
    return file_manager.create_legacy_zip(job_id)


def _build_attribution_text(university: str, year: str, subject: str, author: str) -> str:
    parts = [
        (university or "").strip() or "不明",
        (year or "").strip() or "不明",
        (subject or "").strip() or "不明",
        (author or "").strip() or "不明",
    ]
    return " ".join(parts)
