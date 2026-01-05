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
# ==================

if [[ ! -f "$JOB_CSV" ]]; then
  echo "ERROR: job csv not found: $JOB_CSV" >&2
  exit 2
fi

mkdir -p "$OUT_DIR"
cd "$OUT_DIR" || exit 1

echo "JOB_CSV : $JOB_CSV"
echo "OUT_DIR : $OUT_DIR"
echo

# 1行目ヘッダを除外して読む
# CSVの4列目(job_id)だけ使う（空はスキップ）
tail -n +2 "$JOB_CSV" | while IFS=, read -r pdf_path basename year job_id; do
  # ダブルクォート除去
  job_id="${job_id%\"}"
  job_id="${job_id#\"}"

  if [[ -z "$job_id" ]]; then
    continue
  fi

  echo "=== DOWNLOAD: $job_id"
  curl -sS -u "${BASIC_USER}:${BASIC_PASS}" --fail -L -OJ \
    "${DOWNLOAD_BASE}/${job_id}/download"
done

echo
echo "DONE. downloaded files are in: $OUT_DIR"