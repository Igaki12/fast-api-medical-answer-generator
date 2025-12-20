import base64
import json
import pathlib
import sys
import subprocess
import time
import random
import os
import shutil
import urllib.request
import urllib.error

try:
  import requests
except ModuleNotFoundError:
  requests = None
from typing import Any

USING_GENAI_SDK = True
genai: Any = None
types: Any = None
genai_errors: Any = None
try:
  from google import genai as genai_sdk # type: ignore
  from google.genai import types as genai_types # type: ignore
  from google.genai import errors as genai_errors_sdk # type: ignore
  genai = genai_sdk
  types = genai_types
  genai_errors = genai_errors_sdk
except ModuleNotFoundError:
  USING_GENAI_SDK = False
# 他、pandocをbrewなどでインストールしておく必要があります。


class RestAPIError(Exception):
  def __init__(self, status_code, message):
    super().__init__(message)
    self.code = status_code
    self.message = message


class _FallbackErrors:
  APIError = RestAPIError


# リクエストが15分を超えたらタイムアウト扱い（ミリ秒）
HTTP_TIMEOUT_MS = 15 * 60 * 1000
# 再試行対象のサーバー系ステータスコード
RETRYABLE_STATUS = {500, 502, 503, 504}
MODEL_NAME = "gemini-3-pro-preview"
REST_API_VERSION = "v1alpha"
REST_API_ROOT = "https://generativelanguage.googleapis.com"


def _resolve_api_key():
  key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
  if not key:
    print("ジェミニのAPIキーをエクスポートしてください")
    sys.exit(1)
  return key


API_KEY = _resolve_api_key()
client = None
if USING_GENAI_SDK:
  try:
    client = genai.Client(
      api_key=API_KEY,
      http_options=types.HttpOptions(api_version=REST_API_VERSION, timeout=HTTP_TIMEOUT_MS)
    )
  except Exception as exc:
    print(f"google-genai SDK の初期化に失敗しました（{exc}）。REST API で再試行します。")
    USING_GENAI_SDK = False
    genai_errors = _FallbackErrors

API_ERROR_CLASSES = (RestAPIError,)
if USING_GENAI_SDK and genai_errors not in (None, _FallbackErrors):
  API_ERROR_CLASSES = (genai_errors.APIError, RestAPIError)

# Retrieve and encode the PDF byte
if len(sys.argv) < 2:
  print("Usage: python run_pipeline.py <pdf_file_path> <output_directory> 第一引数に PDFファイルのパスを指定してください。第二引数は出力ディレクトリ（省略時は output-runPipelinePy/markdown）")
  sys.exit(1)

filepath = pathlib.Path(sys.argv[1])
output_directory = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path("output-runPipelinePy/markdown")
output_directory.mkdir(parents=True, exist_ok=True)
# 大文字の .PDF が指定された場合も小文字 .pdf にリネームして処理を継続
if filepath.suffix == ".PDF":
    new_filepath = filepath.with_suffix(".pdf")
    os.rename(filepath, new_filepath)
    filepath = new_filepath
    print(f"Renamed to: {filepath}")
# 大文字の .DOCX/.DOC が指定された場合も小文字 .docx/.doc にリネームして処理を継続
elif filepath.suffix in [".DOCX", ".DOC"]:
    new_filepath = filepath.with_suffix(filepath.suffix.lower())
    os.rename(filepath, new_filepath)
    filepath = new_filepath
    print(f"Renamed to: {filepath}")

# oneshot_pipeline.sh 側で処理対象をログ出力しているためここでは重複出力を避ける
suffix = filepath.suffix.lower()
# ファイルが画像であれば、 sips コマンドでPDFに変換する
if suffix in ['.png', '.jpg', '.jpeg', '.tiff', '.PNG', '.JPG', '.JPEG', '.TIFF']:
  try:
    # macOS標準搭載の sips コマンドでPDFに変換
    subprocess.run(["sips", "-s", "format", "pdf", str(filepath), "--out", str(filepath.with_suffix('.pdf'))], check=True)
    filepath = filepath.with_suffix('.pdf')
    print(f"Converted image to PDF: {filepath}")

  except subprocess.CalledProcessError:
    print("sips command failed. Please make sure sips is available (macOS標準搭載).")
    sys.exit(1)
  except FileNotFoundError:
    print("sips not found. This command is available on macOS by default.")
    sys.exit(1)


if suffix in ['.docx', '.doc']:
  # まず LibreOffice (soffice) を優先して .doc/.docx → PDF に変換する
  soffice_candidates = [
    shutil.which("soffice"),
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",  # macOS (App bundle 直叩き)
  ]
  soffice_path = next((p for p in soffice_candidates if p and pathlib.Path(p).exists()), None)

  if soffice_path:
    try:
      # writer_pdf_Export を明示。FilterData は複雑なのでまずはデフォルト（堅牢性重視）
      subprocess.run([
        soffice_path, "--headless",
        "--convert-to", "pdf:writer_pdf_Export",
        "--outdir", str(filepath.parent),
        str(filepath)
      ], check=True)
      filepath = filepath.with_suffix('.pdf')
      print(f"Converted via LibreOffice: {filepath}")
    except subprocess.CalledProcessError:
      print("LibreOffice (soffice) によるPDF変換に失敗。pandocでのフォールバックを試みます…")
      try:
        subprocess.run([
          "pandoc", str(filepath),
          "-f", "docx",
          "-o", str(filepath.with_suffix('.pdf')),
          "--pdf-engine=lualatex",
          "-V", "documentclass=ltjsarticle",
          "--include-in-header=header-lua.tex"
        ], check=True)
        filepath = filepath.with_suffix('.pdf')
        print(f"Converted Word document to PDF via pandoc: {filepath}")
      except subprocess.CalledProcessError:
        print("pandoc での PDF 変換も失敗しました。ファイルの破損や互換性を確認してください。")
        sys.exit(1)
      except FileNotFoundError:
        print("pandoc が見つかりません。macOS: brew install pandoc / Ubuntu: sudo apt-get install pandoc")
        sys.exit(1)
  else:
    # soffice が見つからない場合は、pandoc にフォールバック
    print("LibreOffice (soffice) が見つかりません。pandoc での変換を試みます…")
    try:
      subprocess.run([
        "pandoc", str(filepath),
        "-f", "docx",
        "-o", str(filepath.with_suffix('.pdf')),
        "--pdf-engine=lualatex",
        "-V", "documentclass=ltjsarticle",
        "--include-in-header=header-lua.tex"
      ], check=True)
      filepath = filepath.with_suffix('.pdf')
      print(f"Converted Word document to PDF via pandoc: {filepath}")
    except subprocess.CalledProcessError:
      print("pandoc での PDF 変換に失敗しました。LibreOffice をインストールして再実行してください。")
      print("macOS: brew install --cask libreoffice / Ubuntu: sudo apt-get install libreoffice")
      sys.exit(1)
    except FileNotFoundError:
      print("pandoc が見つかりません。macOS: brew install pandoc / Ubuntu: sudo apt-get install pandoc")
      sys.exit(1)

try:
  pdf_bytes = filepath.read_bytes()
except Exception as e:
  print(f"Failed to read PDF bytes: {e}")
  sys.exit(1)
pdf_base64 = base64.b64encode(pdf_bytes).decode("ascii")

prompt = f"添付ファイルは医科大学の過去問問題ファイルです。以下の条件を満たすように、すべての問題に対する解答と解説をMarkdown形式で作成してください。   「{filepath.name}の解答解説」から出力し始めてください。問題ごとに問題番号と問題文を省略せずそのまま引用し、引用であることをはっきりさせるためにquoteをつけてください。ただし問題文に図が含まれる場合、図の部分は引用しなくて構いません。　解説は医学生向けに、冗長を最大限許容して丁寧に網羅的に作成してください。問題文が英語の場合は、解説に問題文の日本語訳についても出力してください。"

# 全部の問題に対しての回答を生成をサボっている場合に、Geminiが出力する無効なテキストを除外するためのキーワード
# これらのキーワードが含まれる場合、無効な回答とみなして再試行する
invalid_keywords = ['同様の手順', '同様の処理', '同様の方法', '以下同様', '残りの問題','以降の解答','以降の解説','以降、文字数制限','指示に従い順次作成','順次作成','同様に作成','（続く）','(以降、各','同様の詳細な解説','続きの解答解説','(以降、全て','(以降、すべて','(以降、同様の','（以降の問題も同様']
max_retries = 3 # やり直しを行う最大回数
response = None

def _build_request_contents():
  """Gemini 3 Pro Preview (v1alpha) expects Content objects with Part payloads."""
  if not USING_GENAI_SDK or types is None:
    raise RuntimeError("google-genai SDK が利用できないため REST API を使用してください。")
  return types.Content(
    role="user",
    parts=[
      types.Part(
        inline_data=types.Blob(
          mime_type='application/pdf',
          data=pdf_bytes,
        ),
      ),
      types.Part(text=prompt),
    ],
  )


def _build_rest_payload():
  return {
    "contents": [
      {
        "role": "user",
        "parts": [
          {
            "inline_data": {
              "mime_type": "application/pdf",
              "data": pdf_base64,
            }
          },
          {
            "text": prompt,
          },
        ],
      }
    ]
  }


def _call_rest_generate_content():
  url = f"{REST_API_ROOT}/{REST_API_VERSION}/models/{MODEL_NAME}:generateContent"
  headers = {
    "Content-Type": "application/json",
    "x-goog-api-key": API_KEY,
  }
  payload = _build_rest_payload()
  timeout_s = HTTP_TIMEOUT_MS / 1000

  if requests:
    try:
      resp = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
    except requests.Timeout as exc:
      raise TimeoutError(str(exc))
    except requests.RequestException as exc:
      raise RuntimeError(f"REST API request failed: {exc}")

    if resp.status_code >= 400:
      err_text = resp.text
      try:
        err_json = resp.json()
        err_text = err_json.get("error", {}).get("message", err_text)
      except ValueError:
        pass
      raise RestAPIError(resp.status_code, err_text)
    return resp.json()

  # Fallback: urllib (requests unavailable)
  data = json.dumps(payload).encode("utf-8")
  req = urllib.request.Request(url, data=data, headers=headers, method="POST")
  try:
    with urllib.request.urlopen(req, timeout=timeout_s) as response:
      body = response.read().decode("utf-8")
      status = response.status
  except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8", errors="ignore")
    status = exc.code
  except urllib.error.URLError as exc:
    raise RuntimeError(f"REST API request failed: {exc}")

  if status >= 400:
    err_text = body
    try:
      err_json = json.loads(body)
      err_text = err_json.get("error", {}).get("message", err_text)
    except Exception:
      pass
    raise RestAPIError(status, err_text)
  try:
    return json.loads(body)
  except json.JSONDecodeError as exc:
    raise RuntimeError(f"Failed to parse REST response: {exc}")

def _extract_text(resp):
  """
  GenerateContentResponse から連結されたテキストを堅牢に抽出します。
  resp.text が空の場合（最初のパートがコードやツールなど非テキストの場合など）は、
  候補の content parts を結合して返します。
  """
  if isinstance(resp, dict):
    t = resp.get("text") or resp.get("output_text")
    if t:
      return t
    texts = []
    for cand in (resp.get("candidates", []) or []):
      content = cand.get("content") or {}
      for part in (content.get("parts", []) or []):
        txt = part.get("text") if isinstance(part, dict) else None
        if txt:
          texts.append(txt)
    return "\n".join(texts).strip()

  # Prefer the SDK's convenience accessor when it's non-empty.
  t = getattr(resp, "text", None)
  if t:
    return t

  # Fallback: join all text parts across all candidates.
  texts = []
  for cand in (getattr(resp, "candidates", []) or []):
    content = getattr(cand, "content", None)
    for part in (getattr(content, "parts", []) or []):
      txt = getattr(part, "text", None)
      if txt:
        texts.append(txt)
  return "\n".join(texts).strip()

# プロンプトを含むリクエストを送信 
for attempt in range(max_retries):
  try:
    if USING_GENAI_SDK and client:
      response = client.models.generate_content(
        model=MODEL_NAME,
        contents=_build_request_contents(),
        config=types.GenerateContentConfig(
          http_options=types.HttpOptions(timeout=HTTP_TIMEOUT_MS)
        ) if types is not None else None
      )
    else:
      response = _call_rest_generate_content()
  except API_ERROR_CLASSES as e:
    code = getattr(e, "code", None)
    msg = getattr(e, "message", str(e))
    if code in RETRYABLE_STATUS and attempt < max_retries - 1:
      # 指数バックオフ + ジッター（最大30秒）
      delay = min((2 ** attempt) + random.uniform(0, 1), 30)
      print(f"Server error {code}: {msg}. Retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
      time.sleep(delay)
      continue
    else:
      # 最終試行または非リトライ系エラーは再送しない
      raise
  except Exception as e:
    # タイムアウトや接続切断等を包括的に判定
    emsg = str(e)
    is_timeout_like = isinstance(e, TimeoutError) or any(x in emsg for x in [
      'DEADLINE_EXCEEDED', 'Timeout', 'ReadTimeout', 'Server disconnected'
    ])
    if is_timeout_like and attempt < max_retries - 1:
      delay = min((2 ** attempt) + random.uniform(0, 1), 30)
      print(f"Request timed out/connection dropped. Retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
      time.sleep(delay)
      continue
    else:
      raise
  
  # Extract text safely (handles mixed non-text parts in candidates)
  resp_text = _extract_text(response)
  if resp_text and not any(keyword in resp_text for keyword in invalid_keywords):
    break
  
  if attempt < max_retries - 1:
      tail = (resp_text[-50:] if resp_text else "")
      print(f"Last 50 characters of response text: {tail}")
      if not resp_text:
        print(f"Response is empty, retrying... (attempt {attempt + 1}/{max_retries})")
      else:
        # レスポンステキストの最後の100文字を表示して、無効なテキストが含まれているか確認
        print(f"Response contains invalid text, retrying... (attempt {attempt + 1}/{max_retries})")
  else:
    # 2回目の方が出力が良くなると言われているので、迷った場合は最後のレスポンスを使用
    print("Max retries reached, using last response")

if not response or not resp_text:
  print("Response is empty, exiting.")
  sys.exit(1)

# print(resp_text)
# Save the response to a markdown file
output_dir = output_directory # pathlib.Path("output-runPipelinePy/markdown")
output_dir.mkdir(parents=True, exist_ok=True)

output_filename = filepath.stem + "_解答解説.md"
output_path = output_dir / output_filename

with open(output_path, 'w', encoding='utf-8') as f:
  f.write(resp_text or "")

print(f"## Finished generating answer markdown: {output_path} ##")




# Changelog
# 2025-10-01 Ver1.0 - 初版 （run_pipeline-v5.8.py を分割。この後にmetadata付与を行うため）
# 2025-10-01 Ver1.1 - 第二引数で出力ディレクトリを指定可能に（デフォルトは従来の output-runPipelinePy/markdown、親フォルダが無ければ作成）
# 2025-10-03 Ver1.2 - 画像ファイル入力の時に、拡張子が大文字でも認識するように。プロンプトにタイトル付与の指示を追加。1行目に無駄な合いの手が入らないように。
# 2025-10-04 Ver1.3 - プロンプトを改良：pathlib.Path.name でファイル名のみを取得してタイトルに使用するように。PDF変換の際に、拡張子が大文字の .PDF/.DOCX/.DOC を小文字にリネームして処理を継続するように。
# 2025-10-20 Ver1.4 - プロンプトを改良：「問題ごとに問題番号と問題文を引用し、引用であることをはっきりさせるためにquoteをつけてください。」を追加 invalid_keywords に '（続く）','(以降、各' などを追加
# 2025-10-21 Ver1.5 - invalid_keywords に '同様の詳細な解説' を追加 プロンプトを変更：よりそのまま引用できるように
# 2025-11-07 Ver1.6 - プロンプトを微修正：図の部分は引用しなくても良いことを明記　図を引用しようとして勝手に手元の画像をPDFに出力するコードを貼り付けてしまう問題を回避
# 2025-11-08 Ver1.7 - oneshot_pipeline.shとログが重複しないようProcessing file出力をスクリプト側で抑制
# 2025-11-12 Ver1.8 - invalid_keywords に '(以降、全て','(以降、すべて','(以降、同様の','（以降の問題も同様' を追加 試行回数を3回に増加
# 2025-12-08 Ver2.0 - Gemini 3 Pro Preview に対応 プロンプトを対応するように微修正
# 2025-12-10 Ver2.1 - Gemini v1alpha API に追随（api_version を v1alpha に更新し、Contents/Parts 形式で PDF + プロンプトを送信）
# 2025-12-13 Ver2.2 - REST API 呼び出し部分を修正（requests が利用可能な場合は requests を使用、利用不可の場合は urllib にフォールバック）突然の ModuleNotFoundError を回避
