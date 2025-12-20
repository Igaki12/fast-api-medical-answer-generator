import os
import sys
import pathlib
import subprocess
import re
import typing

"""
convert_md_to_pdfs.py
MarkdownファイルをMicrosoft Word(docx)およびPDFに変換する。
pandocを利用。引数は <markdown_file|directory|files...> のみ。出力先は file=親の親、dir=親の直下に /docx および /pdf を作成する。
ver2.1で add_metadata.py が生成したサイドカーYAMLから引用脚注ラベルを自動取得するように変更。
"""

# ==== 設定 ======================================================
# 環境変数でも上書き可能：BLOCKQUOTE_ATTRIBUTION="...your text..."
_ENV_BLOCKQUOTE_ATTRIBUTION = os.environ.get("BLOCKQUOTE_ATTRIBUTION")
if _ENV_BLOCKQUOTE_ATTRIBUTION is not None:
    _ENV_BLOCKQUOTE_ATTRIBUTION = _ENV_BLOCKQUOTE_ATTRIBUTION.strip()
DEFAULT_BLOCKQUOTE_ATTRIBUTION = _ENV_BLOCKQUOTE_ATTRIBUTION or "大学 年度 試験科目不明"
DOCX_PANDOC_INPUT_FORMAT = "gfm-yaml_metadata_block-raw_html"
# PDF生成時のMarkdown入力フォーマット（GFM相当の拡張を保持しつつ raw_tex を許可）
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
    "+raw_tex" # 脚注をつけるため必須。消してはいけない
)
# ===============================================================

# v3.6: 特定の記号をASCIIへ確実に落とし、サロゲートペア領域の絵文字を除去してpandoc/pdftexの警告を回避
SPECIAL_REPLACEMENTS_V36 = {
    "☐": "[ ]",  # U+2610
    "☑": "[x]",  # U+2611
    "🔘": "(●)",  # U+1F518
    "⚪": "( )",  # U+26AA
    "⬜": "[ ]",  # U+2B1C
}
ASTRAL_RE = re.compile(r"[\U00010000-\U0010FFFF]")


def sanitize_symbols_v36(text: str) -> str:
    for src, dst in SPECIAL_REPLACEMENTS_V36.items():
        text = text.replace(src, dst)
    return ASTRAL_RE.sub("", text)

from pathlib import Path
import logging

logger = logging.getLogger(__name__)

_METADATA_KEYS = ("大学名", "年度", "試験科目")


def build_blockquote_attribution(data: typing.Mapping[str, typing.Any]) -> str:
    """大学名・年度・試験科目から脚注ラベルを生成。欠損は「不明」で補う。"""
    parts: list[str] = []
    for key in _METADATA_KEYS:
        raw = data.get(key, "") if hasattr(data, "get") else ""
        if raw is None:
            text = ""
        elif isinstance(raw, str):
            text = raw.strip()
        else:
            text = str(raw).strip()
        parts.append(text or "不明")
    return " ".join(parts)


def _find_metadata_yaml(md_path: Path) -> typing.Optional[Path]:
    """対象Markdownに対応するサイドカーYAMLを探索する。"""
    base_name = f"{md_path.stem}_metadata.yaml"
    candidates: list[Path] = []
    seen: set[Path] = set()
    for parent in [md_path.parent, *md_path.parents]:
        for candidate in (parent / base_name, parent / "metadata-yaml" / base_name):
            if candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _load_metadata_from_yaml(yaml_path: Path) -> dict[str, typing.Any]:
    """サイドカーYAMLからメタデータを読み込む（PyYAMLが無い場合は簡易解析）。"""
    try:
        text = yaml_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("metadata 読み込みに失敗: %s (%s)", yaml_path, exc)
        return {}

    data: dict[str, typing.Any] = {}
    try:
        import yaml  # type: ignore
    except Exception:
        yaml = None

    if yaml is not None:
        try:
            loaded = yaml.safe_load(text)
            if isinstance(loaded, dict):
                data = loaded
        except Exception as exc:
            logger.debug("PyYAMLでの読み込みに失敗: %s (%s)", yaml_path, exc)

    if not data:
        for line in text.splitlines():
            if ":" not in line:
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            if key in _METADATA_KEYS:
                data[key] = value.strip()

    return data


def resolve_blockquote_attribution(md_path: Path) -> tuple[str, str, typing.Optional[Path], list[str]]:
    """
    BLOCKQUOTE_ATTRIBUTION を決定する。
    優先順位: 環境変数 > サイドカーYAML > 既定値（全て不明）。
    戻り値は (脚注テキスト, ソース種別, 使用したYAMLパス, 不明扱いキー)。
    """
    if _ENV_BLOCKQUOTE_ATTRIBUTION:
        return DEFAULT_BLOCKQUOTE_ATTRIBUTION, "environment", None, []

    yaml_path = _find_metadata_yaml(md_path)
    if yaml_path:
        metadata = _load_metadata_from_yaml(yaml_path)
        missing: list[str] = []
        for key in _METADATA_KEYS:
            raw = metadata.get(key)
            if isinstance(raw, str):
                text = raw.strip()
            elif raw is None:
                text = ""
            else:
                text = str(raw).strip()
            if not text:
                missing.append(key)
        attr = build_blockquote_attribution(metadata)
        return attr, "metadata", yaml_path, missing

    return DEFAULT_BLOCKQUOTE_ATTRIBUTION, "fallback", None, list(_METADATA_KEYS)


def _inject_attribution_to_blockquotes(md_text: str, attribution_text: str) -> str:
    """
    Markdownテキスト内の blockquote（先頭が '>'）の“各塊”の末尾に、
    指定の脚注（TeX）を raw_tex として追記する。
    すでに \begin{flushright} や attribution 本文が含まれている場合は二重付与を避ける。
    """
    lines = md_text.splitlines(keepends=False)
    out: list[str] = []
    i = 0
    n = len(lines)

    # 追記する quoted TeX スニペット（blockquote 内に入れるので '>' を付与）
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
        # blockquote の開始判定：空白→'>' のパターンも許容
        if line.lstrip().startswith(">"):
            # blockquote ブロックを収集
            block: list[str] = []
            while i < n and lines[i].lstrip().startswith(">"):
                block.append(lines[i])
                i += 1

            # 末尾重複防止チェック（すでに脚注っぽいものがあるか）
            joined_tail = "\n".join(block[-10:]) if block else ""
            existing_markers = [attribution_text]
            if DEFAULT_BLOCKQUOTE_ATTRIBUTION and DEFAULT_BLOCKQUOTE_ATTRIBUTION not in existing_markers:
                existing_markers.append(DEFAULT_BLOCKQUOTE_ATTRIBUTION)
            has_attr = (
                "\\begin{flushright}" in joined_tail
                or "\\QuoteAttribution" in joined_tail
                or any(marker and marker in joined_tail for marker in existing_markers)
            )

            if not has_attr:
                block.extend(quoted_snippet(attribution_text))

            out.extend(block)
            # ここで次行は非 '>'（blockquote の外）なので、そのままループ継続
            continue

        out.append(line)
        i += 1

    return "\n".join(out) + ("\n" if md_text.endswith("\n") else "")


def _find_closing_delimiter(text: str, start_idx: int, open_ch: str, close_ch: str) -> typing.Optional[int]:
    """start_idx から始まる括弧の対応位置を返す。ネストとエスケープを考慮。"""
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


def _strip_markdown_images(md_text: str) -> tuple[str, list[str]]:
    """Markdownの ![]() / ![][] 画像を削除し、削除内容を返す。"""
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
            alt_text = md_text[i + 2 : alt_close]
            j = alt_close + 1
            while j < n and md_text[j].isspace():
                j += 1
            if j < n and md_text[j] == "(":
                target_close = _find_closing_delimiter(md_text, j, "(", ")")
                if target_close is None:
                    out.append(ch)
                    i += 1
                    continue
                target = md_text[j + 1 : target_close].strip()
                summary = f"markdown:{alt_text.strip() or '(no alt)'} -> {target or '(empty)'}"
                removals.append(summary)
                i = target_close + 1
                continue
            if j < n and md_text[j] == "[":
                label_close = _find_closing_delimiter(md_text, j, "[", "]")
                if label_close is None:
                    out.append(ch)
                    i += 1
                    continue
                label = md_text[j + 1 : label_close].strip()
                summary = f"markdown_ref:{alt_text.strip() or '(no alt)'}[{label or '(implicit)'}]"
                removals.append(summary)
                i = label_close + 1
                continue
        out.append(ch)
        i += 1

    return "".join(out), removals


def strip_markdown_images_only(md_text: str) -> tuple[str, list[str]]:
    """Markdown画像記法のみを除去し、削除ログを返す。"""
    return _strip_markdown_images(md_text)


def _log_sanitization(stage: str, source: Path, logs: list[str]) -> None:
    if not logs:
        return
    head = ", ".join(logs[:3])
    tail = "" if len(logs) <= 3 else f", ... (+{len(logs) - 3})"
    print(
        f"[info] Removed {len(logs)} embedded image snippet(s) for {stage}: {head}{tail} (source: {source})"
    )


def create_image_sanitized_copy(
    src_md_path: Path, suffix: str = ".no_images.md"
) -> tuple[Path, list[str]]:
    """
    Markdownを読み込み、Markdown画像記法を除去したファイルを
    /markdown_sanitized に保存してパスと削除ログを返す。
    削除対象が無ければ元ファイルパスを返す。
    """
    text = src_md_path.read_text(encoding="utf-8")
    sanitized, logs = strip_markdown_images_only(text)
    if sanitized == text:
        return src_md_path, []

    sanitized_dir = src_md_path.parent / "markdown_sanitized"
    sanitized_dir.mkdir(parents=True, exist_ok=True)
    tmp_name = src_md_path.stem + suffix
    tmp_path = sanitized_dir / tmp_name
    tmp_path.write_text(sanitized, encoding="utf-8")
    return tmp_path, logs


def _find_front_matter_end(lines: list[str]) -> typing.Optional[int]:
    """YAMLフロントマターがあれば終了行の“次”のインデックスを返す。"""
    if not lines:
        return None
    if lines[0].strip() != "---":
        return None
    for idx in range(1, len(lines)):
        stripped = lines[idx].strip()
        if stripped in {"---", "..."}:
            return idx + 1
    return None


def _normalize_horizontal_rules_for_pdf(md_text: str) -> str:
    """
    Pandocの markdown+yaml_metadata_block では、文中の '---' 単独行が
    YAMLメタデータとして誤解されうるため、PDF用テンポラリでは '***' に置換する。
    ※フロントマター（先頭の --- ... --- ）は保持する。
    """
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


def add_attribution_to_blockquotes_file(
    src_md_path: Path,
    attribution_text: str,
    suffix: str = ".with_attrib.md",
) -> tuple[Path, list[str]]:
    """
    入力 Markdown を読み、Markdownファイル冒頭に画像についての注意書きを追加。
    さらに、blockquote 末尾に脚注を追加した加工 Markdown を
    ファイル: /markdown_with_attrib に保存してパスを返す。
    """
    src_md_path = Path(src_md_path)
    try:
        text = src_md_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.exception("Markdown読み込みに失敗: %s", src_md_path)
        raise

    logs: list[str] = []
    try:
        injected = _inject_attribution_to_blockquotes(text, attribution_text)
        new_text = _normalize_horizontal_rules_for_pdf(injected)
        # さらに冒頭に注意書きを追加
        citation = "※画像の読解については、モデルの特性上、実際の所見と異なる解釈や不正確な説明が出力されるリスクがございます。臨床判断・教育評価・公式文書等への転用に際しては、必ず原資料および一次情報を再確認し、専門家のレビューを経た上で慎重にご利用ください。"
        # 冒頭に注意書きが追加されていない場合のみ追加
        if citation not in new_text:
            new_text = f"**{citation}**\n\n" + new_text

        sanitized_text, logs = strip_markdown_images_only(new_text)
        sanitized_text = sanitize_symbols_v36(sanitized_text)

    except Exception as e:
        logger.exception("blockquote 脚注の自動追記でエラー: %s", e)
        raise

    # フォルダ： markdown_with_attrib がなければ作成
    attrib_dir = src_md_path.parent / "markdown_with_attrib"
    try:
        attrib_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.exception("脚注付き Markdown 用ディレクトリの作成に失敗: %s", attrib_dir)
        raise
    # ファイルを新規作成して保存（オリジナルは変更しない）
    tmp_name = src_md_path.stem + suffix
    tmp_path = attrib_dir / tmp_name
    try:
        tmp_path.write_text(sanitized_text, encoding="utf-8")
    except Exception as e:
        logger.exception("加工 Markdown の書き出しに失敗: %s", tmp_path)
        raise

    return tmp_path, logs


def _build_pandoc_env(tmp_base: pathlib.Path) -> dict:
    """pandoc用に安全な一時ディレクトリを環境変数で指定する。
    macOSでTMPDIRが /private/var/folders/zz/zyxvpxvq6csfxvn_n0000000000000/T のような
    グローバル領域を指すと、createDirectory: permission denied が起こりうるため、
    出力ベース直下に専用tmpを作って固定する。
    """
    env = os.environ.copy()
    try:
        tmp_base.mkdir(parents=True, exist_ok=True)
    except Exception:
        # 作成に失敗しても以降のsubprocessで上書きされるだけなので握りつぶす
        pass
    env["TMPDIR"] = str(tmp_base)
    env["TMP"] = str(tmp_base)
    env["TEMP"] = str(tmp_base)
    return env


def _normalize_stem(stem: str) -> str:
    """"_解答解説"が含まれていなければ付与して重複を避ける。"""
    return stem if "_解答解説" in stem else f"{stem}_解答解説"


def _calc_output_root_for_input_path(p: pathlib.Path) -> pathlib.Path:
    """入力がファイルなら親の親、ディレクトリなら親を出力ベースとする。"""
    if p.is_dir():
        return p.parent
    gp = p.parent.parent
    # ルート直下などで親の親が同一となる場合のフォールバック
    return gp if gp != p.parent else p.parent


def convert_one(filepath: pathlib.Path, output_root: pathlib.Path) -> None:
    """単一Markdownをdocx/pdfへ変換する。出力は output_root/{docx,pdf} 配下。"""
    pandoc_env = _build_pandoc_env(output_root / ".pandoc-tmp")
    original_md_path = Path(filepath)
    md_for_pdf_path: Path = original_md_path
    attribution_text, attr_source, attr_yaml_path, missing_keys = resolve_blockquote_attribution(original_md_path)

    if attr_source == "environment":
        print(f"[info] BLOCKQUOTE_ATTRIBUTION を環境変数から使用します: {attribution_text}")
    elif attr_source == "metadata":
        source_note = str(attr_yaml_path) if attr_yaml_path else "metadata"
        if missing_keys:
            missing = "、".join(missing_keys)
            print(f"[info] BLOCKQUOTE_ATTRIBUTION をメタデータ ({source_note}) から取得: {attribution_text} （欠損: {missing} → \"不明\" として利用）")
        else:
            print(f"[info] BLOCKQUOTE_ATTRIBUTION をメタデータ ({source_note}) から取得: {attribution_text}")
    else:
        print(f"[warn] BLOCKQUOTE_ATTRIBUTION のメタデータが見つからず既定値を使用します: {attribution_text}")

    docx_input_path = original_md_path
    docx_logs: list[str] = []
    try:
        docx_input_path, docx_logs = create_image_sanitized_copy(
            original_md_path, suffix=".docx.no_images.md"
        )
    except Exception as exc:
        print(f"[warn] docx用の画像除去に失敗。元のMarkdownを使用します: {exc}")
        docx_input_path = original_md_path
        docx_logs = []
    _log_sanitization("docx", original_md_path, docx_logs)

    # Word(docx)
    try:
        docx_output_dir = output_root / "docx"
        docx_output_dir.mkdir(parents=True, exist_ok=True)
        base = _normalize_stem(filepath.stem)
        docx_output_path = docx_output_dir / f"{base}.docx"
        subprocess.run(
            [
                "pandoc",
                str(docx_input_path),
                "-f",
                DOCX_PANDOC_INPUT_FORMAT,
                "-o",
                str(docx_output_path),
            ],
            check=True,
            env=pandoc_env,
        )
        print(f"Converted to Word document: {docx_output_path}")
        try:
            md_for_pdf_path, pdf_logs = add_attribution_to_blockquotes_file(
                src_md_path=original_md_path,
                attribution_text=attribution_text,
                suffix=".with_attrib.md",
            )
            _log_sanitization("pdf", original_md_path, pdf_logs)
            print(f"[info] blockquote 脚注を付与した Markdown を生成: {md_for_pdf_path.name}")
        except Exception as e:
            print(f"[warn] blockquote 脚注付与に失敗。元の Markdown で継続します: {e}")
            md_for_pdf_path = docx_input_path
    except subprocess.CalledProcessError:
        print("pandoc command failed. Please make sure pandoc is installed.")
    except FileNotFoundError:
        print("pandoc not found. Please install pandoc first.")
        print("Install with: brew install pandoc (macOS) or apt install pandoc (Ubuntu)")

    # PDF
    try:
        pdf_output_dir = output_root / "pdf"
        pdf_output_dir.mkdir(parents=True, exist_ok=True)
        base = _normalize_stem(filepath.stem)
        pdf_output_path = pdf_output_dir / f"{base}.pdf"
        subprocess.run(
            [
                "pandoc",
                str(md_for_pdf_path),
                "-f",
                PDF_PANDOC_INPUT_FORMAT,
                "-o",
                str(pdf_output_path),
                "--pdf-engine=lualatex",
                "-V",
                "documentclass=ltjsarticle",
                "--include-in-header=header-lua.tex",
                "--include-in-header=header-quote-bg.tex",
            ],
            check=True,
            env=pandoc_env,
        )
        print(f"Converted to PDF document: {pdf_output_path}")
    except subprocess.CalledProcessError:
        print("pandoc command failed. Please make sure pandoc is installed.")
    except FileNotFoundError:
        print("pandoc not found. Please install pandoc first.")
        print("Install with: brew install pandoc (macOS) or apt install pandoc (Ubuntu)")


if len(sys.argv) < 2:
    print(
        "Usage: python3 convert_md_to_pdfs.py <markdown_file|directory|files...> "
        "各入力に対して、出力先は markdownファイル=その親の親ディレクトリ／ディレクトリ=その親ディレクトリ の直下に /docx と /pdf を作成します。"
    )
    sys.exit(1)

args = sys.argv[1:]
candidate_paths = [pathlib.Path(a) for a in args]

tasks: list[tuple[pathlib.Path, pathlib.Path]] = []
for p in candidate_paths:
    if p.is_dir():
        out_root = _calc_output_root_for_input_path(p)
        md_list = sorted(p.glob("*.md"))
        for md in md_list:
            tasks.append((md, out_root))
    elif p.is_file():
        if p.suffix.lower() in {".md", ".markdown", ".mdown"}:
            out_root = _calc_output_root_for_input_path(p)
            tasks.append((p, out_root))
        else:
            print(f"[skip] Not a markdown file: {p}")
    else:
        print(f"[warn] Not found: {p}")

if not tasks:
    print("[error] No markdown files to convert. 指定したパスに .md が見つかりません。")
    sys.exit(1)

for md, out_root in tasks:
    print(f"[convert] {md} -> {out_root}")
    convert_one(md, out_root)

# Changelog
# 2025-10-01: ver1.0 Initial version (run_pipeline.py-v5.8から分割して作成)
# 2025-10-01: ver1.1 アウトプットディレクトリをコマンドライン引数で指定可能に変更
# 2025-10-03: ver1.2 ディレクトリ/複数ファイル/ワイルドカード入力に対応。末尾引数が既存ディレクトリの場合は出力ベースとして扱う。"_解答解説" の重複付与を抑止。
# 2025-10-03: ver1.3 macOSのTMPDIR権限問題に対処。pandoc実行時の一時ディレクトリを output_root/.pandoc-tmp に固定して Permission denied を回避（pandocのオプションは不変更）。
# 2025-10-03: ver1.4 引数を入力パス群のみ(<markdown_file|directory|files...>)に簡素化。出力先は file=親の親、dir=親 とし、それぞれ直下に /docx と /pdf を作成（pandocオプションは不変更）。
# 2025-10-19: ver1.7 新たに引用文に対して背景を変更して見やすくするような .txtファイルを作成し さらに引用文の末尾に 機械的に客注をつけるような コードを追加
# 2025-10-19: ver1.8 PDF生成用のpandoc入力を raw_tex 可能なMarkdown拡張に切り替え、blockquote脚注の自動追記を安定化
# 2025-10-19: ver1.9 PDF用テンポラリで '---' 水平線を '***' に変換し YAML誤検知を回避
# 2025-10-20: ver2.0 blockquote脚注付きMarkdownの保存先を /markdown_with_attrib に変更 なければ作成
# 2025-10-21: ver2.1 サイドカーYAMLから大学名・年度・試験科目を取得して脚注ラベルを自動生成し、欠損時は「不明」で継続
# 2025-10-23: ver2.2 +hard_line_breaks をPDF用pandoc入力に追加 → 改行の扱いをGFM準拠に改善
# 2025-10-24: ver2.3 冒頭に画像についての注意書きを追加 → 太字に変更
# 2025-10-24: ver2.4 DOCX/PDF入力をサニタイズして画像・HTML・\\includegraphicsを無視し、検出ログを出力。pandoc入力フォーマットから raw_html を無効化。
# 2025-11-08: ver2.5 サニタイズ対象をMarkdown画像記法のみに限定し、HTMLテキストの誤削除を防止。
# 2025-11-08: ver2.6 ログ出力を若干改善。
# 2025-12-16: ver3.5 weasyprint 廃止に伴い以前の pandoc + lualatex による PDF 生成に戻す。
# 2025-12-16: ver3.6 PDF用Markdownの書き出し時に特定記号のASCII置換とサロゲートペア除去を追加し、pandoc/pdftexの警告を抑制。
