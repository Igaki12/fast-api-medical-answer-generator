from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


PDF_PANDOC_INPUT_FORMAT = (
    "markdown"
    "+hard_line_breaks"
    "+yaml_metadata_block"
    "+gfm_auto_identifiers"
    "+pipe_tables"
    "+table_captions"
    "+strikeout"
    "+task_lists"
    "+definition_lists"
    "+fenced_code_blocks"
    "+auto_identifiers"
    "+footnotes"
    "+raw_tex"
)

SPECIAL_REPLACEMENTS_V36 = {
    "☐": "[ ]",
    "☑": "[x]",
    "🔘": "(●)",
    "⚪": "( )",
    "⬜": "[ ]",
}
ASTRAL_RE = re.compile(r"[\U00010000-\U0010FFFF]")

HEADER_PANDOC = Path(__file__).resolve().parent / "pandoc-header-v1.0.tex"


def convert_markdown_to_pdf(md_path: Path, output_dir: Path, attribution_text: str) -> Path:
    if not HEADER_PANDOC.exists():
        raise RuntimeError("Pandoc header file is missing in app/services/legacy.")

    md_text = md_path.read_text(encoding="utf-8")
    md_text = _inject_attribution(md_text, attribution_text)
    md_text = _normalize_horizontal_rules_for_pdf(md_text)
    md_text, _ = _strip_markdown_images(md_text)
    md_text = _sanitize_symbols(md_text)

    tmp_dir = output_dir / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{md_path.stem}.with_attrib.md"
    tmp_path.write_text(md_text, encoding="utf-8")

    pandoc_env = _build_pandoc_env(output_dir / ".pandoc-tmp")
    pdf_output_dir = output_dir / "pdf"
    pdf_output_dir.mkdir(parents=True, exist_ok=True)
    base = md_path.stem
    pdf_path = pdf_output_dir / f"{base}.pdf"

    subprocess.run(
        [
            "pandoc",
            str(tmp_path),
            "-f",
            PDF_PANDOC_INPUT_FORMAT,
            "-o",
            str(pdf_path),
            "--pdf-engine=lualatex",
            "-V",
            "documentclass=ltjsarticle",
            "--include-in-header",
            str(HEADER_PANDOC),
        ],
        check=True,
        env=pandoc_env,
    )
    return pdf_path


def _build_pandoc_env(tmp_base: Path) -> dict:
    env = os.environ.copy()
    try:
        tmp_base.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    env["TMPDIR"] = str(tmp_base)
    env["TMP"] = str(tmp_base)
    env["TEMP"] = str(tmp_base)
    return env


def _sanitize_symbols(text: str) -> str:
    for src, dst in SPECIAL_REPLACEMENTS_V36.items():
        text = text.replace(src, dst)
    return ASTRAL_RE.sub("", text)


def _inject_attribution(md_text: str, attribution_text: str) -> str:
    citation = (
        "※画像の読解については、モデルの特性上、実際の所見と異なる解釈や不正確な説明が出力されるリスクがございます。"
        "臨床判断・教育評価・公式文書等への転用に際しては、必ず原資料および一次情報を再確認し、専門家のレビューを経た上で慎重にご利用ください。"
    )
    if citation not in md_text:
        md_text = f"**{citation}**\n\n{md_text}"
    injected = _inject_attribution_to_blockquotes(md_text, attribution_text)
    return injected


def _inject_attribution_to_blockquotes(md_text: str, attribution_text: str) -> str:
    lines = md_text.splitlines(keepends=False)
    out: list[str] = []
    i = 0
    n = len(lines)

    def quoted_snippet(attr: str) -> list[str]:
        return [
            ">",
            "> \\par\\vspace{0.8\\baselineskip}",
            "> \\begin{flushright}\\footnotesize",
            f"> --- {attr}",
            "> \\end{flushright}",
        ]

    while i < n:
        line = lines[i]
        if line.lstrip().startswith(">"):
            block: list[str] = []
            while i < n and lines[i].lstrip().startswith(">"):
                block.append(lines[i])
                i += 1

            joined_tail = "\n".join(block[-10:]) if block else ""
            has_attr = (
                "\\begin{flushright}" in joined_tail
                or "\\QuoteAttribution" in joined_tail
                or (attribution_text and attribution_text in joined_tail)
            )
            if not has_attr:
                block.extend(quoted_snippet(attribution_text))
            out.extend(block)
            continue

        out.append(line)
        i += 1

    return "\n".join(out) + ("\n" if md_text.endswith("\n") else "")


def _normalize_horizontal_rules_for_pdf(md_text: str) -> str:
    lines = md_text.splitlines(keepends=False)
    front_matter_end = _find_front_matter_end(lines)
    if front_matter_end is None:
        front_matter_end = 0
    prefix = lines[:front_matter_end]
    body = lines[front_matter_end:]

    normalized_body: list[str] = []
    for line in body:
        stripped = line.strip()
        if stripped and set(stripped) <= {"-"} and len(stripped) >= 3:
            leading = line[: len(line) - len(line.lstrip())]
            normalized_body.append(f"{leading}***")
        else:
            normalized_body.append(line)

    merged = prefix + normalized_body
    return "\n".join(merged) + ("\n" if md_text.endswith("\n") else "")


def _find_front_matter_end(lines: list[str]) -> int | None:
    if not lines:
        return None
    if lines[0].strip() != "---":
        return None
    for idx in range(1, len(lines)):
        stripped = lines[idx].strip()
        if stripped in {"---", "..."}:
            return idx + 1
    return None


def _strip_markdown_images(md_text: str) -> tuple[str, list[str]]:
    removals: list[str] = []
    out: list[str] = []
    i = 0
    n = len(md_text)

    while i < n:
        ch = md_text[i]
        if (
            ch == "!"
            and (i == 0 or md_text[i - 1] != "\\")
            and i + 1 < n
            and md_text[i + 1] == "["
        ):
            alt_close = _find_closing_delimiter(md_text, i + 1, "[", "]")
            if alt_close is None:
                out.append(ch)
                i += 1
                continue
            j = alt_close + 1
            while j < n and md_text[j].isspace():
                j += 1
            if j < n and md_text[j] == "(":
                target_close = _find_closing_delimiter(md_text, j, "(", ")")
                if target_close is None:
                    out.append(ch)
                    i += 1
                    continue
                removals.append("inline-image")
                i = target_close + 1
                continue
            if j < n and md_text[j] == "[":
                label_close = _find_closing_delimiter(md_text, j, "[", "]")
                if label_close is None:
                    out.append(ch)
                    i += 1
                    continue
                removals.append("ref-image")
                i = label_close + 1
                continue
        out.append(ch)
        i += 1

    return "".join(out), removals


def _find_closing_delimiter(text: str, start_idx: int, open_ch: str, close_ch: str) -> int | None:
    depth = 0
    i = start_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None
