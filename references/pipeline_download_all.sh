#!/usr/bin/env bash
set -euo pipefail

# ====== 設定 ======
DOWNLOAD_BASE="${DOWNLOAD_BASE:-http://127.0.0.1:8000/api/v1/pipeline}"
BASIC_USER="${BASIC_USER:-dev}"
BASIC_PASS="${BASIC_PASS:-dev}"

# 入力CSV（リクエストスクリプトが出力したもの）
JOB_CSV="${1:-./job_ids.csv}"

# 保存先（Downloads）
OUT_DIR="${OUT_DIR:-/Users/embryo03/Downloads}"
# マージ先（Downloads配下）
MERGE_TIMESTAMP="$(date +"%Y%m%d-%H%M%S")"
MERGE_DIR="${MERGE_DIR:-${OUT_DIR}/pipeline-merged-${MERGE_TIMESTAMP}}"
# ==================

if [[ ! -f "$JOB_CSV" ]]; then
  echo "ERROR: job csv not found: $JOB_CSV" >&2
  exit 2
fi

mkdir -p "$OUT_DIR"
cd "$OUT_DIR" || exit 1

declare -a JOB_IDS=()
JOB_ID_SEEN="|"

echo "JOB_CSV : $JOB_CSV"
echo "OUT_DIR : $OUT_DIR"
echo

# 1行目ヘッダを除外して読む
# CSVの4列目(job_id)だけ使う（空はスキップ）
while IFS=, read -r pdf_path basename year job_id; do
  # ダブルクォート除去
  job_id="${job_id%\"}"
  job_id="${job_id#\"}"

  if [[ -z "$job_id" ]]; then
    continue
  fi

  if [[ "$JOB_ID_SEEN" != *"|${job_id}|"* ]]; then
    JOB_IDS+=("$job_id")
    JOB_ID_SEEN="${JOB_ID_SEEN}${job_id}|"
  fi

  echo "=== DOWNLOAD: $job_id"
  curl -sS -u "${BASIC_USER}:${BASIC_PASS}" --fail -L -OJ \
    "${DOWNLOAD_BASE}/${job_id}/download"
done < <(tail -n +2 "$JOB_CSV")

echo
echo "DONE. downloaded files are in: $OUT_DIR"

echo
echo "=== MERGE: extracting zip files and collecting pdf/markdown ==="
mkdir -p "${MERGE_DIR}/pdf" "${MERGE_DIR}/markdown"

for job_id in "${JOB_IDS[@]}"; do
  zip_path="${OUT_DIR}/${job_id}.zip"
  if [[ ! -f "$zip_path" ]]; then
    echo "SKIP: zip not found: $zip_path" >&2
    continue
  fi

  echo "MERGE: $zip_path"
  tmp_dir="$(mktemp -d)"
  unzip -q "$zip_path" -d "$tmp_dir"

  if [[ -d "${tmp_dir}/pdf" ]]; then
    cp -f "${tmp_dir}/pdf/"* "${MERGE_DIR}/pdf/" 2>/dev/null || true
  fi
  if [[ -d "${tmp_dir}/markdown" ]]; then
    cp -f "${tmp_dir}/markdown/"* "${MERGE_DIR}/markdown/" 2>/dev/null || true
  fi

  rm -rf "$tmp_dir"
done

echo "DONE. merged outputs are in: $MERGE_DIR"
