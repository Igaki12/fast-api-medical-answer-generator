from __future__ import annotations

import os
import random
import subprocess
import time
from pathlib import Path

from google import genai # type: ignore
from google.genai import types # type: ignore


HTTP_TIMEOUT_MS = 15 * 60 * 1000
MAX_RETRIES = 2
MODEL_NAME = os.getenv("GEMINI_LEGACY_MODEL", "gemini-3-pro-preview")
REST_API_VERSION = os.getenv("GEMINI_LEGACY_API_VERSION", "v1alpha")

INVALID_KEYWORDS = [
    "同様の手順",
    "同様の処理",
    "同様の方法",
    "以下同様",
    "残りの問題",
    "以降の解答",
    "以降の解説",
    "以降、文字数制限",
    "指示に従い順次作成",
    "順次作成",
    "同様に作成",
    "（続く）",
    "(以降、各",
    "同様の詳細な解説",
    "続きの解答解説",
    "(以降、全て",
    "(以降、すべて",
    "(以降、同様の",
    "（以降の問題も同様",
]


def generate_markdown_from_input(
    input_path: Path,
    output_dir: Path,
    api_key: str | None,
    explanation_name: str,
    university: str,
    year: str,
    subject: str,
    author: str,
) -> Path:
    resolved_key = _resolve_api_key(api_key)
    pdf_path = _ensure_pdf(input_path)
    pdf_bytes = pdf_path.read_bytes()
    prompt = _build_prompt(
        explanation_name=explanation_name,
        filename=pdf_path.name,
        university=university,
        year=year,
        subject=subject,
        author=author,
    )

    client = genai.Client(
        api_key=resolved_key,
        http_options=types.HttpOptions(api_version=REST_API_VERSION, timeout=HTTP_TIMEOUT_MS),
    )
    contents = types.Content(
        role="user",
        parts=[
            types.Part(
                inline_data=types.Blob(
                    mime_type="application/pdf",
                    data=pdf_bytes,
                ),
            ),
            types.Part(text=prompt),
        ],
    )

    response_text = _generate_with_retry(client, contents)
    output_dir.mkdir(parents=True, exist_ok=True)
    base = _normalize_base_name(explanation_name, pdf_path)
    md_path = output_dir / f"{base}.md"
    md_path.write_text(response_text, encoding="utf-8")
    return md_path


def _resolve_api_key(request_key: str | None) -> str:
    key = request_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("Gemini API key is required (api_key or GEMINI_API_KEY).")
    return key


def _ensure_pdf(input_path: Path) -> Path:
    path = _normalize_extension(input_path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return path
    if suffix in {".png", ".jpg", ".jpeg", ".tiff"}:
        return _convert_image_to_pdf(path)
    raise ValueError(f"Unsupported input file type: {path.suffix}")


def _normalize_extension(path: Path) -> Path:
    suffix = path.suffix
    if suffix and suffix != suffix.lower():
        new_path = path.with_suffix(suffix.lower())
        path.rename(new_path)
        return new_path
    return path


def _convert_image_to_pdf(path: Path) -> Path:
    output_path = path.with_suffix(".pdf")
    try:
        subprocess.run(
            ["sips", "-s", "format", "pdf", str(path), "--out", str(output_path)],
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("sips is required to convert images to PDF on macOS.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Failed to convert image to PDF.") from exc
    return output_path


def _build_prompt(
    explanation_name: str,
    filename: str,
    university: str,
    year: str,
    subject: str,
    author: str,
) -> str:
    title = explanation_name.strip() or filename
    return (
        "添付ファイルは医科大学の過去問問題ファイルです。以下の条件を満たすように、すべての問題に対する解答と解説をMarkdown形式で作成してください。"
        f"「{title}の解答解説」から出力し始めてください。問題ごとに問題番号と問題文を省略せずそのまま引用し、引用であることをはっきりさせるためにquoteをつけてください。"
        "ただし問題文に図が含まれる場合、図の部分は引用しなくて構いません。解説は医学生向けに、冗長を許容して丁寧に網羅的に作成してください。"
        "問題文が英語の場合は、解説に問題文の日本語訳についても出力してください。"
    )


def _generate_with_retry(client: genai.Client, contents: types.Content) -> str:
    response_text = ""
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(
                    http_options=types.HttpOptions(timeout=HTTP_TIMEOUT_MS),
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=False,
                        maximum_remote_calls=30,
                        ignore_call_history=False,
                    ),
                ),
            )
            response_text = _extract_text(response)
        except Exception as exc:
            last_error = exc
            response_text = ""
        if response_text and not _contains_invalid_keyword(response_text):
            return response_text
        if attempt < MAX_RETRIES - 1:
            delay = min((2**attempt) + random.uniform(0, 1), 30)
            time.sleep(delay)
    if not response_text:
        if last_error:
            raise RuntimeError(f"Gemini request failed after retries. from last_error: {last_error}") from last_error
        raise RuntimeError("Gemini response is empty.")
    return response_text


def _extract_text(response: object) -> str:
    text = getattr(response, "text", None)
    if text:
        return text
    texts: list[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                texts.append(part_text)
    return "\n".join(texts).strip()


def _contains_invalid_keyword(text: str) -> bool:
    return any(keyword in text for keyword in INVALID_KEYWORDS)


def _normalize_base_name(explanation_name: str, pdf_path: Path) -> str:
    base = explanation_name.strip() or pdf_path.stem
    base = base.replace("/", "_").replace("\\", "_")
    base = Path(base).stem
    if "解答" not in base:
        base = f"{base}_解答解説"
    return base
