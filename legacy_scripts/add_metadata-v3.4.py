#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_metadata.py

既存のMarkdown解答・解説ファイル（.md）からメタデータを抽出し、
サイドカーYAMLはデフォルトで各入力ファイルの「親フォルダの親」直下の `metadata-yaml/` に保存します（--yaml-dir 指定時はそのディレクトリに保存）。
※入力ファイルは一切変更しません（--emit-md を指定した場合のみコピーを生成）。

依存:
  - google-genai (from google import genai / from google.genai import types)
  - （任意）PyYAML があれば厳密検証。無ければ正規表現で簡易検証。

環境変数:
  - GOOGLE_API_KEY を事前にエクスポートしてください。
  % source secret_export_gemini_api_key.sh

使用例:
  python3 add_metadata.py output-PoC-g1-Kobe/markdown output-PoC-g2-Kobe/markdown
  python3 add_metadata.py path/to/file1.md path/to/file2.md --emit-md
"""

import argparse
import datetime as dt
import os
import re
import sys
import pathlib
import random
import time
import signal
import json
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List

USING_GENAI_SDK = True
try:
    from google import genai # type: ignore
    from google.genai import types # type: ignore
    from google.genai import errors as genai_errors # type: ignore
except ModuleNotFoundError:
    USING_GENAI_SDK = False
    genai = None
    types = None
    genai_errors = None

# google-genai SDK の型が不足する古いバージョンでは SDK を無効化して REST にフォールバック
if USING_GENAI_SDK:
    required_attrs = ("GenerateContentConfig", "HttpOptions")
    if types is None or any(not hasattr(types, attr) for attr in required_attrs):
        print("警告: google-genai SDK が古いため REST API へフォールバックします。", file=sys.stderr)
        USING_GENAI_SDK = False
        genai_errors = None


# ---- グローバル設定 ----
class RestAPIError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.code = status_code
        self.message = message


class _FallbackErrors:
    APIError = RestAPIError


HTTP_TIMEOUT_MS = 10 * 60 * 1000  # 10分
RETRYABLE_STATUS = {500, 502, 503, 504}
MODEL_NAME = "gemini-2.5-flash"
REST_API_VERSION = "v1"
REST_API_ROOT = "https://generativelanguage.googleapis.com"

# YAML必須キー（「問題数」は廃止。代わりに「最初の問題番号」「最後の問題番号」を採用）
REQUIRED_KEYS = ["大学名", "年度", "試験科目", "最初の問題番号", "最後の問題番号", "参照ファイルパス", "生成日時", "エンティティリスト"]

# 中断要求（SIGINT/SIGTERM）用のフラグとハンドラ
STOP_REQUESTED = False

def _resolve_api_key():
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        print("エラー: Google Gemini APIキーをエクスポートしてください（GOOGLE_API_KEY もしくは GEMINI_API_KEY）。", file=sys.stderr)
        sys.exit(1)
    return key


API_KEY = _resolve_api_key()
_client = None
if USING_GENAI_SDK and genai is not None and types is not None:
    try:
        _client = genai.Client(
            api_key=API_KEY,
            http_options=types.HttpOptions(api_version=REST_API_VERSION, timeout=HTTP_TIMEOUT_MS)
        )
    except Exception as exc:
        print(f"警告: google-genai SDK の初期化に失敗したため REST API へフォールバックします（{exc}）。", file=sys.stderr)
        USING_GENAI_SDK = False
        genai_errors = _FallbackErrors

API_ERROR_CLASSES = (RestAPIError,)
if USING_GENAI_SDK and genai_errors not in (None, _FallbackErrors):
    API_ERROR_CLASSES = (genai_errors.APIError, RestAPIError)


def _request_stop(signum, frame):
    """SIGINT/SIGTERMを受け取ったらフラグを立て、現在のファイル処理が終わり次第停止する。"""
    global STOP_REQUESTED
    if not STOP_REQUESTED:
        STOP_REQUESTED = True
        try:
            name = signal.Signals(signum).name
        except Exception:
            name = str(signum)
        print(f"[info] 受信: {name}. 現在のファイル処理が完了次第、中断します。")


def load_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def ensure_client():
    """SDKクライアントを返す（RESTフォールバック時は None）。"""
    return _client if USING_GENAI_SDK else None


def build_prompt(file_path: str, file_text: str) -> str:
    """
    メタデータ抽出プロンプト。
    - YAMLフロントマターのみを返す（--- から --- まで）
    - エンティティリストは、文章に現れた“固有名詞”をそのまま抜き出す
      （医学・学術に関する固有名詞を優先、20件以内、重複排除、頻度順）
    - 最初の問題番号と最後の問題番号を本文から抽出。大問番号と小問番号（存在する場合）は両方含め、本文の表記を忠実に用いた“一義的に特定できる”ラベルで返す（例: 「第1問/問1」「Q1/(a)」「1-(1)」「I-2」など）。小問が無い場合は大問のみ。
    - 不明項目は空欄にせず、合理的に推定（例: 大学名/科目名はファイル名からの推量可）
    - 参照ファイルパスと生成日時はプレースホルダで返す（後でスクリプト側で上書き）
    """
    template = f"""あなたは厳格なメタデータ抽出器です。以下の入力（ファイルパス・本文）から、指定のYAMLフロントマターのみを返してください。説明文やコードブロックは一切不要です。返答は先頭行に'---'、末尾行に'---'を付けたYAMLのみ。

# 入力
[ファイルパス]
{file_path}

[本文（抜粋可・ただし根拠は本文からのみ）]
{file_text}

# 出力要件（YAMLフロントマターのみ）
---
大学名: <本文またはファイル名・親フォルダ名から推定。公立/私立名の表記揺れは避け、正式名称 日本の大学>
年度: <西暦4桁。本文やファイル名から推定。例: 2023>
学年: <本文またはファイル名から推定。1年生|2年生|3年生|4年生|5年生|6年生|その他 のいずれか1つだけ>
試験科目: <本文またはファイル名から推定。医科大学にあるような科目名。>
最初の問題番号: <本文で最初に出現する問題の一義的番号。大問・小問を含める。本文の表記を忠実に。例: "第1問/問1", "Q1/(a)", "1-(1)">
最後の問題番号: <本文で最後に出現する問題の一義的番号。大問・小問を含める。本文の表記を忠実に。>
参照ファイルパス: __TO_BE_FILLED_BY_SCRIPT__
生成日時: __TO_BE_FILLED_BY_SCRIPT__
エンティティリスト:
  # 文章中の“固有名詞”を抽出。医学・学術に関する固有名詞を優先。
  # 重複排除、本文に出ない語は厳禁。頻度順の降順で並べる。
  - <固有名詞1>
  - <固有名詞2>
  - <固有名詞3>
---

# 厳格な制約
- YAML以外の文字や注釈は一切出力しない。
- コードフェンス（```）やMarkdown記法は使わない。
- 半角/全角、ギリシャ文字、上付き/下付き、記号も本文に合わせる。
- リストのハイフンは必ずASCIIの半角 '-' を用いる。
- 「最初の問題番号」「最後の問題番号」は、小問しか明示されない場合でも大問の識別が可能なら含める（見出しや文脈から）。ただし本文に無い情報の創作は禁止。表記は本文の実際のラベルを尊重する（例: 「第3問」「問2」「(b)」「1-(2)」「Q5」等）。
"""
    return template


def _build_sdk_contents(prompt: str):
    if not USING_GENAI_SDK or types is None:
        raise RuntimeError("google-genai SDK が利用できないため REST API を使用してください。")
    return types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt)],
    )


def _build_rest_payload(prompt: str):
    return {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                ],
            }
        ]
    }


def _call_rest_generate_content(prompt: str):
    payload = _build_rest_payload(prompt)
    url = f"{REST_API_ROOT}/{REST_API_VERSION}/models/{MODEL_NAME}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": API_KEY,
    }
    timeout_s = HTTP_TIMEOUT_MS / 1000
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"REST API request failed: {exc}")

    if status >= 400:
        err = body
        try:
            err_json = json.loads(body)
            err = err_json.get("error", {}).get("message", err)
        except Exception:
            pass
        raise RestAPIError(status, err)
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse REST response: {exc}")


def _extract_text(resp):
    if isinstance(resp, dict):
        t = resp.get("text") or resp.get("output_text")
        if t:
            return t
        texts: List[str] = []
        for cand in (resp.get("candidates", []) or []):
            content = cand.get("content") or {}
            for part in (content.get("parts", []) or []):
                txt = part.get("text") if isinstance(part, dict) else None
                if txt:
                    texts.append(txt)
        return "\n".join(texts).strip()

    text = getattr(resp, "text", None)
    if text:
        return text
    texts = []
    for cand in getattr(resp, "candidates", []) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", []) or []:
            txt = getattr(part, "text", None)
            if txt:
                texts.append(txt)
    return "\n".join(texts).strip()


def call_gemini(client, prompt: str, max_retries: int = 3) -> str:
    """
    Geminiへプロンプトを送り、YAMLフロントマターらしい応答を得るまでリトライする。
    """
    last_text = ""
    for attempt in range(max_retries):
        try:
            if USING_GENAI_SDK and client:
                cfg = None
                if types and hasattr(types, "GenerateContentConfig") and hasattr(types, "HttpOptions"):
                    cfg = types.GenerateContentConfig(
                        http_options=types.HttpOptions(timeout=HTTP_TIMEOUT_MS)
                    )
                resp = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=_build_sdk_contents(prompt),
                    config=cfg
                )
            else:
                resp = _call_rest_generate_content(prompt)
        except API_ERROR_CLASSES as e:
            code = getattr(e, "code", None)
            msg = getattr(e, "message", str(e))
            if code in RETRYABLE_STATUS and attempt < max_retries - 1:
                delay = min((2 ** attempt) + random.uniform(0, 1), 30)
                print(f"[retryable] {code}: {msg} → {delay:.1f}s 待機して再試行 {attempt+1}/{max_retries-1}")
                time.sleep(delay)
                continue
            raise
        except Exception as e:
            emsg = str(e)
            is_timeout_like = isinstance(e, TimeoutError) or any(x in emsg for x in ['DEADLINE_EXCEEDED', 'Timeout', 'ReadTimeout', 'Server disconnected'])
            if is_timeout_like and attempt < max_retries - 1:
                delay = min((2 ** attempt) + random.uniform(0, 1), 30)
                print(f"[timeout] {emsg} → {delay:.1f}s 待機して再試行 {attempt+1}/{max_retries-1}")
                time.sleep(delay)
                continue
            raise

        last_text = _extract_text(resp) or ""
        if not last_text:
            print("[warn] 応答が空。再試行します。")
            continue

        if last_text.strip().startswith("---") and last_text.strip().rstrip().endswith("---"):
            return last_text

        print("[warn] YAMLフロントマター形式でない可能性。再試行します。")

    # 最後の応答を返す（後段でバリデーションして不可なら失敗扱い）
    return last_text


def try_parse_yaml_block(yaml_text: str) -> Optional[Dict[str, Any]]:
    """
    先頭と末尾の --- に挟まれたYAMLを辞書化。
    PyYAMLがあれば使う。無ければ正規表現で最低限の検証（箇条書き配列のネスト1段に対応）。
    """
    yaml_text = yaml_text.strip()
    m = re.match(r"^---\s*(.*?)\s*---\s*$", yaml_text, flags=re.S)
    if not m:
        return None
    block = m.group(1)

    # 可能ならPyYAMLを使用
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(block)
        return data if isinstance(data, dict) else None
    except Exception:
        pass

    # フォールバック簡易パーサ
    data: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    for raw in block.splitlines():
        line = raw.rstrip("\n")
        # コメント行はスキップ
        if re.match(r"^\s*#", line):
            continue
        # 空行はそのまま継続（リスト継続の可能性がある）
        if re.match(r"^\s*$", line):
            continue

        # リスト要素
        m_item = re.match(r"^\s*-\s+(.*)$", line)
        if m_item:
            if current_list_key is not None:
                item = m_item.group(1).strip()
                if item:
                    data.setdefault(current_list_key, []).append(item)
            # current_list_key が無い場合は無視（不正なYAML想定）
            continue

        # key: value または key: の検出
        m_kv = re.match(r"^\s*([^:\n]+?)\s*:\s*(.*)$", line)
        if m_kv:
            key = m_kv.group(1).strip()
            val = m_kv.group(2).strip()

            # ブラケット配列 [a, b]
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                items = [p.strip() for p in re.split(r",", inner) if p.strip()]
                data[key] = items
                current_list_key = key
                continue

            # 値が空 => 直後のハイフン行で配列が続く想定
            if val == "":
                data[key] = []
                current_list_key = key
                continue

            # 通常のスカラ値
            data[key] = val
            current_list_key = None
            continue

        # ここに到達した行は解釈しない
        continue

    return data if data else None


def _is_unknown_field(val: Any) -> bool:
    """
    空文字/None/「不明」を未確定として扱うヘルパ。
    """
    if val is None:
        return True
    s = str(val).strip()
    return s == "" or s == "不明"



def enforce_and_fill_fields(data: Dict[str, Any], src_path: pathlib.Path, now_iso: str) -> Dict[str, Any]:
    """
    必須キーの存在と最小限の整形を強制。欠損値は空や0ではなく推定値で埋める。
    - 参照ファイルパス/生成日時はスクリプト側で上書き
    - 「最初の問題番号」「最後の問題番号」はモデル出力をそのまま採用（ローカル推定は行わない）
    """
    merged: Dict[str, Any] = {}
    for k in REQUIRED_KEYS:
        merged[k] = data.get(k)

    # 参照ファイルパス・生成日時は強制上書き
    # 表示範囲を「もう一つ上の親」まで拡張：親(0) / 親の親(1) / 親の親の親(2)
    try:
        base = src_path.parents[2]  # 可能なら親の親の親を基準にする
    except IndexError:
        # 親階層が足りない場合は従来の親の親、さらに無ければ親を基準にフォールバック
        try:
            base = src_path.parents[1]
        except IndexError:
            base = src_path.parent
    try:
        rel_path = src_path.relative_to(base)
        merged["参照ファイルパス"] = str(rel_path)
    except Exception:
        # 念のための保険：従来ロジックにフォールバック
        try:
            rel_path = src_path.relative_to(src_path.parent.parent)
            merged["参照ファイルパス"] = str(rel_path)
        except Exception:
            merged["参照ファイルパス"] = src_path.name
    merged["生成日時"] = now_iso

    # 年度は4桁数字を抽出（なければファイル名から推定）
    if not merged.get("年度"):
        m = re.search(r"(20[0-9]{2}|19[0-9]{2})", src_path.name)
        merged["年度"] = m.group(1) if m else ""

    # 試験科目は空ならファイル名から（例: 「細胞生物学」「生化学」「解剖学」等、_解答解説を除去）
    if not merged.get("試験科目"):
        name = src_path.stem
        name = re.sub(r"_?解答解説$", "", name)
        merged["試験科目"] = name

    # 大学名の空はファイル名から推測（漢字+大学 を拾う）
    if not merged.get("大学名"):
        name = src_path.stem
        m = re.search(r"([\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF]+大学)", name)
        merged["大学名"] = m.group(1) if m else ""

    # エンティティリストは配列に正規化
    ents = merged.get("エンティティリスト")
    if isinstance(ents, list):
        # 重複除去（順序維持）
        seen = set()
        uniq = []
        for e in ents:
            if not isinstance(e, str):
                continue
            if e not in seen:
                seen.add(e)
                uniq.append(e)
        merged["エンティティリスト"] = uniq[:20]
    elif isinstance(ents, str) and ents.strip():
        # カンマ区切りなどを想定
        parts = [p.strip() for p in re.split(r"[,\u3001]", ents) if p.strip()]
        merged["エンティティリスト"] = parts[:20]
    else:
        merged["エンティティリスト"] = []

    return merged

def atomic_write_text(target: pathlib.Path, content: str, encoding: str = "utf-8") -> None:
    """同一ディレクトリに一時ファイルを書き、fsync後にos.replaceで原子的に置換する。"""
    tmp = target.with_suffix(target.suffix + ".tmp")
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding=encoding) as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)


def render_front_matter(data: Dict[str, Any]) -> str:
    lines = ["---"]
    lines.append(f"大学名: {data.get('大学名','')}")
    lines.append(f"年度: {data.get('年度','')}")
    lines.append(f"試験科目: {data.get('試験科目','')}")
    lines.append(f"最初の問題番号: {data.get('最初の問題番号','')}")
    lines.append(f"最後の問題番号: {data.get('最後の問題番号','')}")
    lines.append(f"参照ファイルパス: {data.get('参照ファイルパス','')}")
    lines.append(f"生成日時: {data.get('生成日時','')}")
    lines.append("エンティティリスト:")
    ents = data.get("エンティティリスト", [])
    if not isinstance(ents, list):
        ents = []
    for e in ents:
        lines.append(f"  - {e}")
    lines.append("---")
    return "\n".join(lines)


def process_file(client: Any, path: pathlib.Path, out_yaml_dir: Optional[pathlib.Path], emit_md: bool, md_out_dir: pathlib.Path) -> bool:
    print(f"[info] Processing: {path}")
    text = load_text(path)

    # 入力が長すぎる場合は数万文字で打ち切る（モデルの負荷軽減）
    max_chars = 80_000
    text_snippet = text if len(text) <= max_chars else (text[:max_chars] + "\n…(truncated)…")

    prompt = build_prompt(str(path), text_snippet)

    # --- 内容検証付きの再試行ロジック ---
    # 条件: 「大学名」または「試験科目」が空欄または「不明」の場合のみ再試行
    # やり直し回数: 最大2回（= 初回 + 最大2回で合計最大3回）
    max_redo = 2
    attempts: List[tuple] = []  # (idx, resp_text, data_dict_or_None, unknown_flag)
    chosen_resp_text: Optional[str] = None
    chosen_data: Optional[Dict[str, Any]] = None

    for i in range(1, max_redo + 2):  # 1..3
        resp_text = call_gemini(client, prompt)

        if not resp_text.strip():
            print(f"[warn] 応答が空でした（{i}回目）。")
            attempts.append((i, resp_text, None, True))
            # 続行して再試行（上限まで）
            continue

        data = try_parse_yaml_block(resp_text)
        if data is None:
            print(f"[warn] YAMLブロックの抽出に失敗しました（{i}回目）。再試行します。")
            attempts.append((i, resp_text, None, True))
            continue

        unknown = any(_is_unknown_field(data.get(k)) for k in ("大学名", "試験科目"))
        attempts.append((i, resp_text, data, unknown))

        if unknown:
            if i < max_redo + 1:
                print(f"[warn] 大学名/試験科目が未確定（空欄または「不明」）。再試行します… {i}/{max_redo+1}")
                continue
            else:
                # 上限到達
                break
        else:
            # 必須フィールドが埋まっているので採用
            chosen_resp_text = resp_text
            chosen_data = data
            break

    # 全試行で未確定の場合は「2回目の出力結果」を採用
    if chosen_data is None:
        # attempts[1]（0-based）= 2回目
        second = attempts[1] if len(attempts) >= 2 else None
        if second and second[2] is not None:
            print("[info] 2回とも未確定のため、2回目の出力を採用します。")
            resp_text = second[1]
            data = second[2]
        else:
            # 2回目がパース不能だった場合は、最後にパースできたものを採用（保険）
            last_valid = next((t for t in reversed(attempts) if t[2] is not None), None)
            if last_valid is not None:
                print("[info] 2回目の結果が不完全のため、最後の有効なYAMLを採用します。")
                resp_text = last_valid[1]
                data = last_valid[2]
            else:
                print(f"[error] YAMLブロックの抽出に失敗しました（全試行）。: {path}")
                return False
    else:
        resp_text = chosen_resp_text or ""
        data = chosen_data


    # JSTのISO時刻
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("Asia/Tokyo")
    except Exception:
        tz = None
    now = dt.datetime.now(tz) if tz else dt.datetime.utcnow()
    now_iso = now.isoformat(timespec="seconds")

    merged = enforce_and_fill_fields(data, path, now_iso)

    # サイドカーYAML出力（入力は変更しない）
    # 出力先：未指定なら「入力ファイルの親フォルダの親」配下の metadata-yaml/
    target_yaml_dir = out_yaml_dir if out_yaml_dir is not None else (path.parent.parent / "metadata-yaml")
    target_yaml_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = target_yaml_dir / f"{path.stem}_metadata.yaml"
    yaml_text = render_front_matter(merged) + "\n"
    atomic_write_text(yaml_path, yaml_text)
    print(f"[ok] メタデータを書き出しました → {yaml_path}")

    # オプション: フロントマター付きのMDコピーを作る（入力は触らない）
    if emit_md:
        md_out_dir.mkdir(parents=True, exist_ok=True)
        md_copy = md_out_dir / f"{path.stem}_withMetadata.md"
        atomic_write_text(md_copy, yaml_text + "\n" + text)
        print(f"[ok] メタデータ付きMDコピーを作成しました → {md_copy}")

    return True


def collect_md_files(paths: List[str]) -> List[pathlib.Path]:
    files: List[pathlib.Path] = []
    # 引数なしならデフォルトのテストセットを探索
    if not paths:
        defaults = [
            "output-PoC-g1-Kobe/markdown",
            "output-PoC-g2-Kobe/markdown",
        ]
        paths = defaults

    for p in paths:
        pth = pathlib.Path(p)
        if pth.is_dir():
            files.extend(sorted(pth.glob("**/*.md")))
        elif pth.is_file() and pth.suffix.lower() == ".md":
            files.append(pth)
    return files


def main():
    parser = argparse.ArgumentParser(description="Markdown解答・解説からメタデータを抽出してサイドカーYAMLを生成します（入力ファイルは変更しません）")
    parser.add_argument("paths", nargs="*", help="処理対象の.mdファイルまたはディレクトリ（複数可）。未指定なら既定ディレクトリ:output-PoC-g1-Kobe/markdownやoutput-PoC-g2-Kobe/markdownを探索。")
    parser.add_argument("--emit-md", action="store_true", help="メタデータを先頭に付けたMDコピーを output-with-metadata/ に生成（入力は変更しません）")
    parser.add_argument("--yaml-dir", default=None, help="サイドカーYAMLの出力ディレクトリ（未指定なら各入力ファイルの親フォルダの親に 'metadata-yaml/' を自動作成して保存）")
    parser.add_argument("--md-out-dir", default="output-with-metadata", help="--emit-md 時のMDコピー出力ディレクトリ")
    args = parser.parse_args()

    files = collect_md_files(args.paths)
    if not files:
        print("処理対象の.mdファイルが見つかりませんでした。ディレクトリやファイルを指定してください。", file=sys.stderr)
        sys.exit(1)

    client = ensure_client()
    out_yaml_dir = pathlib.Path(args.yaml_dir) if args.yaml_dir else None
    md_out_dir = pathlib.Path(args.md_out_dir)

    # SIGINT/SIGTERM を捕捉して安全に停止
    try:
        signal.signal(signal.SIGINT, _request_stop)
        signal.signal(signal.SIGTERM, _request_stop)
    except Exception:
        # 一部環境（Windows等）ではSIGTERM未サポート
        pass

    successes: List[pathlib.Path] = []
    failures: List[pathlib.Path] = []

    errs = 0
    for f in files:
        if STOP_REQUESTED:
            print("[info] 中断要求を検出。残りのファイルはスキップします。")
            break
        try:
            ok = process_file(client, f, out_yaml_dir, args.emit_md, md_out_dir)
            if ok:
                successes.append(f)
            else:
                errs += 1
                failures.append(f)
        except KeyboardInterrupt:
            print("[warn] キーボード割り込みを検出。安全に終了処理を行います…")
            break
        except Exception as e:
            errs += 1
            failures.append(f)
            print(f"[error] {f}: {e}")

    total_processed = len(successes) + len(failures)
    if STOP_REQUESTED:
        print(f"[done] 中断により終了（成功 {len(successes)}件 / 失敗 {len(failures)}件）")
        sys.exit(130)
    elif errs:
        print(f"[done] 完了（エラー {errs}件）")
        sys.exit(2)
    else:
        print("[done] すべて完了")


if __name__ == "__main__":
    main()


# Changelog
# 2025-09-26 v1 初版 作成
# 2025-09-26 v1.1 モデルを gemini-2.5-flash からgemini-2.5-pro に変更
# 2025-09-26 v1.2 エンティティ抽出を“固有名詞”の抜き出しに変更。問題数を本文から推定に変更
# 2025-09-26 v1.3 プロンプトやコメントの修正 invalid_keywords 削除 要約・医学生難易度追加
# 2025-09-26 v1.4 出力先の既定を「入力ファイルの親の親/metadata-yaml」に変更（--yaml-dir 指定時は従来通り）
# 2025-09-26 v1.5 gemini-2.5-flash に戻す。エンティティリストの上限撤廃
# 2025-09-26 v1.6 大学名・科目名が取得できなければ、call_gemini の応答をやり直しさせるように。YAMLパーサをPyYAML優先に 
# 2025-09-27 v1.7 flashモデルが不安定なのでproに戻す 少しプロンプト修正 学年追加
# 2025-09-27 v1.8 "要約"と"医学生難易度"を削除。プロンプト、必須キー、レンダラーを更新
# 2025-09-27 v1.9 ファイルパスの表示を「親の親」より上を省略するように変更
# 2025-09-27 v2.0 SIGINT/SIGTERMでの安全終了対応・原子的ファイル書き込み導入（部分書き込み防止）
# 2025-09-28 v2.1 "問題数"を廃止し「最初の問題番号」「最後の問題番号」を追加。プロンプト更新。再試行条件に両項目を追加。
# 2025-09-29 v2.2 参照ファイルパスの表示範囲を1階層拡大（親の親の親からの相対パス）に変更
# 2025-09-29 v2.3 抽出結果を用いた引用文をprintする機能を追加（各入力ファイル処理の最後に1行出力）
# 2025-09-29 v2.4 中断時の終了コードを130に変更。エラー時の終了コードを2に変更。末尾の_解答解説.mdを引用文から省略
# 2025-09-30 v2.5 citationの末尾に注意書きを追加（画像読解に関するリスク）
# 2025-10-03 v2.6 citationを解答解説mdファイルの冒頭に追記するように変更 
# 2025-10-03 v2.7 アウトプットディレクトリのパスを、path.parent.parent / "_stem_解答解説完全版.md" に変更
# 2025-10-04 v2.8 citationの末尾の注意書きを改訂 output-dirを /md_with_metadataに変更
# 2025-10-04 v2.9 citationの末尾の注意書きを改訂 citationとcitation2の間に空行を追加
# 2025-10-04 v3.0 引用文章を若干修正
# 2025-10-05 v3.1 citation付きMarkdown生成を廃止し、BLOCKQUOTE_ATTRIBUTION 環境変数を設定するように変更
# 2025-10-05 v3.2 BLOCKQUOTE_ATTRIBUTION の自動設定を廃止し、脚注ラベル生成を convert_md_to_pdfs.py に移管
# 2025-11-08 v3.3 再試行条件から「最初の問題番号」「最後の問題番号」を除外（大学名と試験科目のみ必須）
# 2025-12-13 v3.4 call_gemini のリトライロジックを強化（タイムアウト系エラーも再試行対象に）など、Gemini APIの仕様変更に対応
