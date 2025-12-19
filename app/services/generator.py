from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List

from google import genai


DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")


def generate_explanation(job_id: str, input_path: Path, output_dir: Path) -> List[Path]:
    content = _read_input(input_path)
    markdown = _generate_markdown(content)
    outputs: List[Path] = []

    md_path = output_dir / f"{job_id}.md"
    md_path.write_text(markdown, encoding="utf-8")
    outputs.append(md_path)

    pandoc = _find_pandoc()
    if pandoc:
        outputs.extend(_run_pandoc(pandoc, md_path, output_dir, job_id))

    return outputs


def _read_input(input_path: Path) -> str:
    data = input_path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _generate_markdown(source_text: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Run secret_export_gemini_api_key.sh first.")

    client = genai.Client(api_key=api_key)
    prompt = (
        "You are generating a concise medical exam explanation in Markdown.\n"
        "Provide: 概要, ポイント, 解答プロセス, 注意点.\n"
        "Input:\n"
        f"{source_text}"
    )
    response = client.models.generate_content(model=DEFAULT_MODEL, contents=prompt)
    return response.text or "# Explanation\n\nNo content returned."


def _find_pandoc() -> str | None:
    from shutil import which

    return which("pandoc")


def _run_pandoc(pandoc: str, md_path: Path, output_dir: Path, job_id: str) -> List[Path]:
    outputs: List[Path] = []
    docx_path = output_dir / f"{job_id}.docx"
    pdf_path = output_dir / f"{job_id}.pdf"

    subprocess.run([pandoc, str(md_path), "-o", str(docx_path)], check=True)
    outputs.append(docx_path)

    subprocess.run([pandoc, str(md_path), "-o", str(pdf_path)], check=True)
    outputs.append(pdf_path)
    return outputs
