#!/usr/bin/env bash
# =============================================================================
# secret_export_gemini_api_key.sh
#
# 目的:
# - SCRIPT_DIR 基準で「どこからでも」動く
# - minimum-venv 前提（未有効なら自動 activate）
# - GEMINI_API_KEY を読み込み、Python google-genai で疎通確認して「使えるキー」を 1つ選んで export
# - REST ではなく、google-genai (python) で gemini-3-pro-preview を叩く
#
# 使い方:
#   source ./secret_export_gemini_api_key.sh
#
# 想定:
# - このスクリプトと同じディレクトリ（SCRIPT_DIR）に、キーの候補リストを置ける
#   デフォルト候補ファイル: gemini_api_keys.txt
#   1行に1キー。空行と # コメントは無視。
#
# 既に GEMINI_API_KEY がセットされている場合:
# - そのキーを優先して疎通確認し、OKならそのまま採用
#
# 戻り値（source される前提）:
# - 成功: GEMINI_API_KEY を export して return 0
# - 失敗: 何も export せず return 1
# =============================================================================

set -u  # 未定義変数をエラー（ただし set -e は source 時に事故りやすいので入れない）

# --- detect sourced -----------------------------------------------------------
_is_sourced() {
  [[ "${BASH_SOURCE[0]}" != "${0}" ]]
}

_die() {
  echo "[FATAL] $*" >&2
  if _is_sourced; then
    return 1
  else
    exit 1
  fi
}

# --- script dir ---------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- minimum-venv bootstrap ---------------------------------------------------
VENV_CANDIDATES=(
  "${SCRIPT_DIR}/minimum-venv"
  "${SCRIPT_DIR}/../minimum-venv"
)

VENV_DIR=""
for cand in "${VENV_CANDIDATES[@]}"; do
  if [[ -f "${cand}/bin/activate" ]]; then
    VENV_DIR="${cand}"
    break
  fi
done

[[ -n "${VENV_DIR}" ]] || _die "minimum-venv が見つかりません: ${VENV_CANDIDATES[*]}"

# 既に別venvの場合も含め、minimum-venv でなければ activate
if [[ -z "${VIRTUAL_ENV:-}" || "$(basename "${VIRTUAL_ENV}")" != "minimum-venv" ]]; then
  # shellcheck disable=SC1090
  source "${VENV_DIR}/bin/activate" || _die "venv activate に失敗: ${VENV_DIR}"
fi

PYTHON="${VENV_DIR}/bin/python"
[[ -x "${PYTHON}" ]] || _die "venv python が見つかりません: ${PYTHON}"

# --- config -------------------------------------------------------------------
MODEL_NAME="gemini-3-pro-preview"

# キー候補ファイル（SCRIPT_DIR基準）
KEYFILE_DEFAULT="${SCRIPT_DIR}/gemini_api_keys.txt"

# --- helpers ------------------------------------------------------------------
_mask_key() {
  # 先頭6文字 + … + 末尾4文字（短すぎる場合はそのまま）
  local k="$1"
  local n="${#k}"
  if (( n <= 12 )); then
    echo "${k}"
  else
    echo "${k:0:6}…${k:n-4:4}"
  fi
}

# google-genai 疎通確認（成功なら exit 0）
# - 短いプロンプトで generate_content を呼ぶ
# - 例外を捕まえて非0で返す
_test_key_with_python() {
  local key="$1"
  GEMINI_API_KEY="${key}" "${PYTHON}" - <<'PY'
import os, sys
from google import genai

model = os.environ.get("MODEL_NAME", "gemini-3-pro-preview")
# env var GEMINI_API_KEY を使う前提（google-genai が拾う）
try:
    client = genai.Client()
    resp = client.models.generate_content(
        model=model,
        contents="ping",
    )
    # 念のため text アクセスまで行う（None の場合もあるのでstr化）
    _ = getattr(resp, "text", None)
    print("OK")
    sys.exit(0)
except Exception as e:
    print(f"NG: {type(e).__name__}: {e}")
    sys.exit(1)
PY
}

# --- main ---------------------------------------------------------------------
echo "[env] Using: ${PYTHON} ($(${PYTHON} --version))"
echo "[check] Model: ${MODEL_NAME}"
export MODEL_NAME  # python側で参照

# 1) すでに GEMINI_API_KEY がある場合は最優先で試す
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  echo "[key] GEMINI_API_KEY is already set: $(_mask_key "${GEMINI_API_KEY}")"
  echo "[check] Testing existing key via google-genai..."
  if out="$(_test_key_with_python "${GEMINI_API_KEY}" 2>&1)"; then
    echo "[ok] Existing key works: $(_mask_key "${GEMINI_API_KEY}")"
    # 既にexportされてない可能性があるので明示
    export GEMINI_API_KEY
    if _is_sourced; then return 0; else exit 0; fi
  else
    echo "[warn] Existing key failed: $(_mask_key "${GEMINI_API_KEY}")"
    echo "       ${out}"
    # 既存がダメでも、ファイル候補を試したいので続行
  fi
fi

# 2) ファイルから候補キーを読む
KEYFILE="${GEMINI_KEYFILE:-${KEYFILE_DEFAULT}}"
if [[ "${KEYFILE}" != /* ]]; then
  # 相対指定でもSCRIPT_DIR基準に寄せる
  KEYFILE="${SCRIPT_DIR}/${KEYFILE}"
fi

[[ -f "${KEYFILE}" ]] || _die "キー候補ファイルが見つかりません: ${KEYFILE}
  例: ${KEYFILE_DEFAULT} を作成し、1行に1キーで保存してください（空行/#コメント可）"

echo "[keyfile] Reading: ${KEYFILE}"

# 3) 1つずつ試して、最初にOKのキーを採用
found_key=""
while IFS= read -r line || [[ -n "${line}" ]]; do
  # trim
  k="${line#"${line%%[![:space:]]*}"}"
  k="${k%"${k##*[![:space:]]}"}"
  # skip empty / comment
  [[ -n "${k}" ]] || continue
  [[ "${k:0:1}" != "#" ]] || continue

  masked="$(_mask_key "${k}")"
  echo "[check] Testing key: ${masked}"

  if out="$(_test_key_with_python "${k}" 2>&1)"; then
    echo "[ok] Key works: ${masked}"
    found_key="${k}"
    break
  else
    echo "[ng] Key failed: ${masked}"
    echo "     ${out}"
  fi
done < "${KEYFILE}"

if [[ -z "${found_key}" ]]; then
  _die "有効な GEMINI API key が見つかりませんでした（google-genai で疎通NG）"
fi

export GEMINI_API_KEY="${found_key}"
echo "[done] Set GEMINI_API_KEY: $(_mask_key "${GEMINI_API_KEY}")"

if _is_sourced; then
  return 0
else
  exit 0
fi

# 更新履歴
# ver1.4 google-genai SDK に対応 (旧 REST API 廃止) minimum-venv 前提に変更
# ver1.3 gemini-3-pro-preview に対応 有料アカウント専用モデル
# ver1.2 printfの出力で、表が途中で途切れないように修正
# ver1.1 - 2.5 Pro の権限/制限も同じロジックで確認できるように変更。
# ver1.0 - 初版