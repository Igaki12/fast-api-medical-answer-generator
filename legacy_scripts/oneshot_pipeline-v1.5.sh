#!/usr/bin/env bash
set -euo pipefail

# --- Project root / venv bootstrap -------------------------------------------------
# このスクリプトは「minimum-venv」前提で動かす。
# まだ仮想環境が有効化されていない場合は、ここで自動的に activate する。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/minimum-venv"

# 既に別のvenvに入っている場合は、minimum-venvへ切り替える（安全のため明示）
if [[ -z "${VIRTUAL_ENV:-}" || "$(basename "${VIRTUAL_ENV}")" != "minimum-venv" ]]; then
  if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    # shellcheck disable=SC1090
    source "${VENV_DIR}/bin/activate"
  else
    echo "[FATAL] venv が見つかりません: ${VENV_DIR}"
    echo "        先に作成してください: python3.13 -m venv minimum-venv"
    exit 1
  fi
fi

# venv の python を必ず使う（PATH依存を避ける）
PYTHON="${VENV_DIR}/bin/python"

# 参考: どのPythonで動いているか
echo "[env] Using: ${PYTHON} ($(${PYTHON} --version))"

# ----------------------------------------------------------------------------------

# 使い方: bash oneshot_pipeline.sh <INPUT_DIR> <OUTPUT_DIR> [MISSING_LIST_PATH]
# INPUT_DIR: 入力ディレクトリ (デフォルト: PoC-神戸大学1回生-追加分)
#   過去問ファイル(.pdf)を格納したディレクトリを指定
# OUTPUT_DIR: 出力ディレクトリ (デフォルト: output-PoC-神戸大学1回生-追加分)
#   解答解説MD、最終生成物(docx/pdf)を格納するディレクトリを指定 存在しない場合は新規作成される
# MISSING_LIST_PATH: 未処理ファイルリストのパス (デフォルト: missing_list.txt)
#   パイプライン処理中に作成される未処理ファイルリスト。指定した場合はそのファイルに上書きされる

# Requirements:
# - bash
# - Python 3.13 (venv: minimum-venv)
# - pandoc (for MD to DOCX/PDF conversion)
# - header-lua.tex (for pandoc PDF conversion with header) など
# - libreoffice (for DOCX to PDF conversion)
# - 必要なPythonライブラリ (requirements-min.txt などを参照)
# - secret_export_gemini_api_key.sh: GEMINI_API_KEYをエクスポートするスクリプト
# - check_missing_files.sh: 未処理ファイルリストを生成するスクリプト
# - generate_answer_md.py: 解答解説MDを生成するスクリプト
# - add_metadata.py: 解答解説MDにメタデータを付与するスクリプト
# - convert_md_to_pdfs.py: MDをDOCX/PDFに変換するスクリプト

INPUT_DIR="${1:-PoC-神戸大学1回生-追加分}"
OUTPUT_DIR="${2:-output-PoC-神戸大学1回生-追加分}"
MISSING_LIST_PATH="${3:-missing_list.txt}"
MARKDOWN_DIR="${OUTPUT_DIR}/markdown"

# 出力ディレクトリとMarkdown保存先の事前作成
echo "[step0/5] 出力ディレクトリ準備: ${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"
mkdir -p "${MARKDOWN_DIR}"

echo "[step1/5] APIキーの読込: secret_export_gemini_api_key.sh"
# GEMINI_API_KEY をshellにエクスポート
source "${SCRIPT_DIR}/secret_export_gemini_api_key.sh"

echo "[step2/5] 未処理ファイルの抽出: check_missing_files.sh -> ${MISSING_LIST_PATH}"
MISSING_LIST_PATH="${MISSING_LIST_PATH}" bash "${SCRIPT_DIR}/check_missing_files.sh" "${INPUT_DIR}" "${OUTPUT_DIR}"

if [[ -s "${MISSING_LIST_PATH}" ]]; then
  echo "[step3/5] ファイル単位で Markdown生成 → メタデータ付与 → PDF変換"
  processed=0
  completed=0
  while IFS= read -r f || [[ -n "$f" ]]; do
    # 空行をスキップ
    if [[ -z "${f// }" ]]; then
      continue
    fi
    ((processed++))
    echo "[file ${processed}] Processing: $f"

    if ! "${PYTHON}" "${SCRIPT_DIR}/generate_answer_md.py" "$f" "${MARKDOWN_DIR}"; then
      echo "[ERROR] Markdown生成に失敗: $f"
      continue
    fi

    filename="$(basename "$f")"
    stem="${filename%.*}"
    md_path="${MARKDOWN_DIR}/${stem}_解答解説.md"
    if [[ ! -f "${md_path}" ]]; then
      echo "[ERROR] 生成済みMarkdownが見つかりません: ${md_path}"
      continue
    fi

    if ! "${PYTHON}" "${SCRIPT_DIR}/add_metadata.py" "${md_path}"; then
      echo "[ERROR] メタデータ付与に失敗: ${md_path}"
      continue
    fi

    if ! "${PYTHON}" "${SCRIPT_DIR}/convert_md_to_pdfs.py" "${md_path}"; then
      echo "[ERROR] PDF変換に失敗: ${md_path}"
      continue
    fi

    ((completed++))
    echo "[info] 1ファイル分の処理完了: ${md_path}"
  done < "${MISSING_LIST_PATH}"

  echo "[info] 処理対象 ${processed} 件中 ${completed} 件が完了しました。"
else
  echo "[info] missing_list is empty; nothing to generate"
  exit 0
fi

echo "[step4/5] 引用脚注付きMarkdownの整理"

ATTRIB_WORK_DIR="${OUTPUT_DIR}/markdown/markdown_with_attrib"
if [[ -d "${ATTRIB_WORK_DIR}" ]]; then
  ATTRIB_DEST_DIR="${OUTPUT_DIR}/markdown_with_attrib"
  if [[ -d "${ATTRIB_DEST_DIR}" ]]; then
    SUFFIX="$(date +%Y%m%d-%H%M%S)"
    ATTRIB_DEST_DIR="${OUTPUT_DIR}/markdown_with_attrib_${SUFFIX}"
    echo "[info] 既存の markdown_with_attrib ディレクトリが存在するため、${ATTRIB_DEST_DIR} に退避します"
  fi
  mv "${ATTRIB_WORK_DIR}" "${ATTRIB_DEST_DIR}"
  echo "[info] 引用脚注付きMarkdownを移動しました -> ${ATTRIB_DEST_DIR}"
fi

echo "[done] 全処理完了 -> 出力: ${OUTPUT_DIR}/{docx,pdf}"

# 変更履歴
# ver1.0 - 初版
# ver1.1 - OUTPUT_DIR が存在しない場合に自動作成する処理を追加
# ver1.2 - 説明を充実させた
# ver1.3 - add_metadata.py のサイドカー出力仕様に追従し、convert_md_to_pdfs.py の入力を markdown/ に統一。markdown_with_attrib ディレクトリを出力直下へ移動するように調整。
# ver1.4 - 未処理ファイルを1件ずつ Markdown生成→メタデータ付与→DOCX/PDF変換する順番に変更し、Markdown出力を常に ${OUTPUT_DIR}/markdown へ集約するよう調整。
# ver1.5 - python3 呼び出しを廃止し、minimum-venv を自動 activate（未有効時）して venv の python を常に使用するように修正。スクリプト群を SCRIPT_DIR 基準で呼び出すようにして、実行ディレクトリ依存を低減。