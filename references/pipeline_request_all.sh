#!/usr/bin/env bash
set -euo pipefail

# ====== 設定 ======
API_KEY="${API_KEY:-}"
ENDPOINT="${ENDPOINT:-http://127.0.0.1:8000/api/v1/pipeline}"
BASIC_USER="${BASIC_USER:-dev}"
BASIC_PASS="${BASIC_PASS:-dev}"

# 対象フォルダ（この中の *.pdf を全部送る）
TARGET_DIR="${1:-/Users/embryo03/Documents/medteria/PoC-神戸大学-3回生/PoC-神戸大学-3年_4-3-1_感染症内科}"

UNIVERSITY="${UNIVERSITY:-神戸大学}"
SUBJECT="${SUBJECT:-感染症内科}"
AUTHOR="${AUTHOR:-PoC}"

# job_id 保存先（CSV）
JOB_CSV="${JOB_CSV:-./job_ids.csv}"
# ==================

if [[ -z "$API_KEY" ]]; then
  echo "ERROR: API_KEY が空です。例: export API_KEY='...'" >&2
  exit 2
fi

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "ERROR: TARGET_DIR が存在しません: $TARGET_DIR" >&2
  exit 2
fi

# ヘッダ（上書き）
echo "pdf_path,basename,year,job_id" > "$JOB_CSV"

echo "TARGET_DIR: $TARGET_DIR"
echo "ENDPOINT  : $ENDPOINT"
echo "JOB_CSV   : $JOB_CSV"
echo

shopt -s nullglob
pdfs=( "$TARGET_DIR"/*.pdf )
shopt -u nullglob

if [[ ${#pdfs[@]} -eq 0 ]]; then
  echo "No PDFs found in: $TARGET_DIR" >&2
  exit 0
fi

for f in "${pdfs[@]}"; do
  echo "=== REQUEST: $f"

  BASENAME="$(basename "$f")"
  YEAR="$(printf "%s" "$BASENAME" | grep -oE '[0-9]{4}' | head -n 1 || true)"

  if [[ -z "$YEAR" ]]; then
    echo "[SKIP] year not found in filename: $BASENAME" >&2
    echo "\"$f\",\"$BASENAME\",,\"\"" >> "$JOB_CSV"
    continue
  fi

  JOB_ID="$(
    curl -sS -u "${BASIC_USER}:${BASIC_PASS}" \
      -F "input_file=@${f}" \
      -F "api_key=${API_KEY}" \
      -F "explanation_name=${BASENAME}" \
      -F "university=${UNIVERSITY}" \
      -F "year=${YEAR}" \
      -F "subject=${SUBJECT}" \
      -F "author=${AUTHOR}" \
      "$ENDPOINT" \
    | python3 -c 'import sys, json; print(json.load(sys.stdin).get("job_id",""))'
  )"

  if [[ -z "$JOB_ID" ]]; then
    echo "[FAIL] job_id empty: $BASENAME" >&2
    echo "\"$f\",\"$BASENAME\",\"$YEAR\",\"\"" >> "$JOB_CSV"
    continue
  fi

  echo "JOB_ID=${JOB_ID}"
  echo "\"$f\",\"$BASENAME\",\"$YEAR\",\"$JOB_ID\"" >> "$JOB_CSV"
done

echo
echo "DONE. job ids saved to: $JOB_CSV"
echo "次は download スクリプトで、$JOB_CSV を使ってZIPを一括取得してください。"