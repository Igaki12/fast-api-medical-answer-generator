提示された新しいAPI仕様（メタデータ項目、APIキーの送信方法、画像/PDF入力対応など）を既存の`AGENTS.md`の方針（FastAPI、非同期処理、Python 3.13環境など）に統合しました。

以下が更新された`AGENTS.md`です。

---

# AGENTS.md

## 1. プロジェクト概要

**プロジェクト名**: AI解説生成システム (Prototype)

**目的**: 過去問解説PDFをAIを用いて自動生成するシステムのAPIプロトタイプ構築。

**ターゲット**: 2026年2月までのプロトタイプ完成、およびVPS上のAPIとしての稼働。

**現状フェーズ**: ステップ2（ローカル環境でのAPIプロトタイプ実装・検証）。

---

## 2. 技術スタック

* **言語**: Python **3.13.x**
* **Webフレームワーク**: FastAPI
* 非同期処理 (Async/Await)
* Swagger UI による動作確認


* **サーバー**: Uvicorn (ASGI)
* **AI API**: Google Gemini API (Gemini 3 Pro)
* **python google-genai SDK を使用**
* マルチモーダル入力（PDF, JPEG, PNG）に対応


* **文書変換**:
* Markdown → PDF 変換は **pandoc** を使用
* Python 側では pandoc を subprocess 経由で呼び出す


* **認証**: Basic認証（プロトタイプ段階）
* HTTPS接続を前提とする


* **環境管理**: `minimum-venv` / `requirements-min.txt`

---

## 3. 仮想環境・実行環境の方針（重要）

本プロジェクトでは、**再現性と依存トラブル回避を最優先**とし、以下の仮想環境を正式な実行前提とする。

### 仮想環境

* **仮想環境名**: `minimum-venv`
* **Python バージョン**: **Python 3.13.x**
* **作成方法**:
```bash
python3.13 -m venv minimum-venv

```


* **有効化**:
```bash
source minimum-venv/bin/activate

```



### 運用ルール

* すべての Python スクリプト / FastAPI サーバーは `minimum-venv` 上でのみ実行されることを前提とする
* `python3` / `pip` の直接呼び出しは禁止し、仮想環境内の `python` / `pip` を使用する
* シェルスクリプトは、仮想環境が未有効な場合に自動で `minimum-venv` を `activate` する設計とする

### 依存関係管理

* 依存関係は `requirements-min.txt` に完全固定する
* **作成方法**:
```bash
pip freeze > requirements-min.txt

```


* **別環境での再現**:
```bash
pip install -r requirements-min.txt

```



---

## 4. ディレクトリ構成

本プロジェクトは、Gitで管理するコード/設定とGit管理外のデータ/機密情報を明確に分離する。

```
project-root/
├── .gitignore
├── AGENTS.md
├── requirements-min.txt
├── main.py                  # FastAPIエントリーポイント
│
├── app/
│   ├── auth.py              # Basic認証ロジック
│   ├── models.py            # Pydanticモデル / APIスキーマ定義
│   └── services/
│       ├── file_manager.py  # アップロード/成果物管理
│       └── legacy/
│           ├── convert_markdown.py   # pandoc/LuaLaTeX変換
│           ├── generate_markdown.py  # Gemini呼び出し・Markdown生成
│           ├── pipeline.py           # legacyパイプライン統合
│           └── pandoc-header-v1.0.tex # 統合済みPandocヘッダー
│
├── references/
│   └── (md_files, sh, csv)
│
├── docs/
│   ├── assets/
│   └── meetings/            # ミーティング議事録/進捗報告
│
├── legacy_scripts/          # 既存のワンショット実行スクリプト群
│
└── data/                    # 【Git管理外】
    ├── inputs/              # アップロードされた過去問ファイル(PDF/IMG)
    └── outputs/             # 生成された解説(PDF)

```

---

## 5. 開発・運用ルール

### A. 解説生成・マルチモーダル入力

* **入力**: PDF, JPEG, PNG ファイルをサポート（Wordは変換コスト回避のためステップ2では非対応）。
* **中間処理**: 解説本文は Markdown として生成する。
* **出力**: 最終成果物（PDF）は pandoc により生成する。
* **AIモデル**: Gemini 3 Pro のマルチモーダル機能 (`inlineData`等) を使用して、画像を直接APIへ渡す。

### B. API設計方針（FastAPI）

生成処理は長時間になることが想定されるため、非同期処理（Job Queue方式）を採用する。これによりHTTPタイムアウトを回避する。

1. **Request**: ファイルとメタデータを受け付け、即座に `Job ID` を返す。
2. **Process**: FastAPIの `BackgroundTasks` によりバックグラウンドで生成を実行。
3. **Download**: クライアントは `Job ID` を使ってポーリングを行い、完了次第成果物（PDF）を取得する。

### C. セキュリティ・キー管理

* **API Key**: プロトタイプ段階では柔軟性を高めるため、**リクエストボディ (`multipart/form-data`) 内での `api_key` 送信**をサポートする。
* ※サーバー側の環境変数 `os.environ["GEMINI_API_KEY"]` はフォールバックまたは開発用デフォルトとして保持するが、リクエストパラメータを優先する。



---

## 6. API仕様（v1 Prototype）

### 共通事項

* **認証**: Basic Auth
* **プロトコル**: HTTPS (本番/VPS環境)

### ジョブ状態（status）一覧
* `queued`: 受付済み（バックグラウンド開始待ち）
* `generating_md`: Markdown 生成中
* `generating_pdf`: PDF 生成中
* `done`: PDF 生成完了
* `failed`: 生成失敗
* `failed_to_convert`: 生成時のPDF変換に失敗

### 1. 解説生成リクエスト (POST)

* **URL**: `POST /api/v1/pipeline`
* **Content-Type**: `multipart/form-data`
* **概要**: 過去問ファイルをアップロードし、Markdown生成ジョブを開始する。

**Parameters (Form Data):**

| フィールド名 | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| `api_key` | String | NO | Gemini API Key (未指定時は環境変数フォールバック) |
| `explanation_name` | String | YES | 生成する解説のタイトル (例: 2025年度_東京大学生化学_解答解説, 100文字以内) |
| `year` | String | YES | 年度 (1〜4桁の数字, 例: 2024) |
| `university` | String | YES | 大学名 (例: 東京大学) |
| `subject` | String | YES | 科目名 (例: 生化学) |
| `author` | String | YES | 作成者名 (例: 佐藤先生) |
| `input_file` | File | YES | 問題ファイル (PDF, 20MBまで) |

**Response:**

* **Status**: `202 Accepted`

```json
{
  "status": "accepted",
  "job_id": "exp-20251210-001234",
  "message": "解説生成リクエストを受け付けました。処理が完了したら、ジョブIDを使って結果をダウンロードしてください。"
}

```

**入力チェック（サーバー側）**
- `explanation_name` / `university` / `subject` / `author`: 100文字以内
- `year`: 1〜4桁の数字
- `input_file`: `application/pdf` のみ、拡張子 `.pdf`、20MB以下

### 2. 解説ダウンロード (GET)

* **URL**: `GET /api/v1/pipeline/{job_id}/download`
* **概要**: ジョブIDに基づいて生成状況を確認または成果物をダウンロードする。  
  パイプライン内で Markdown → PDF まで生成済みの成果物を返す。

**Responseパターン:**

1. **処理完了 (Status 200)**
* **Status**: `200 OK`
* **Header**: `Content-Disposition: attachment; filename="{explanation_name}.pdf"`
* **Body**: PDFファイル


2. **処理中 (Status 202)**
* **Status**: `202 Accepted`
* **Body**:
```json
{
  "status": "processing",
  "job_id": "exp-20251210-001234",
  "message": "現在生成処理中です。"
}

```




3. **エラー/不在 (Status 404/409/410)**
* **Status**: `404 Not Found` (ID不一致) または `410 Gone` (有効期限切れ)
* **PDF変換失敗**: `status.json` の `status` が `failed_to_convert` に更新され、ダウンロードは `409 Conflict` を返す



---

## 4. 今後のVPS移行に向けた留意点

* XServer VPS 等へのデプロイを想定
* ローカル起動コマンド:
```bash
uvicorn main:app --reload

```


* アップロードファイルの一時保存先や、生成物の保存先は `data/` ディレクトリ配下とし、定期的なクリーンアップ処理（cron等）を今後検討する。

---

## 5. 次のステップ

実装済み。今後は運用（PDFキャッシュのクリーンアップ運用、監視、UI整備）を優先する。

---

## 6. legacy_scripts 参照ドキュメント

* **`AGENTS_for_legacy_scripts.md`** に、既存の手動/半手動パイプラインの全体像、入出力、出力ディレクトリ構成、環境変数の扱いが整理されています。legacy_scripts を FastAPI に移植する際の要件定義・互換確認の基準として参照すること。
* このリポジトリの `legacy_scripts/` は現状の実装は以下を最新版として扱う:
  * `legacy_scripts/oneshot_pipeline-v1.5.sh`
  * `legacy_scripts/generate_answer_md-v2.2.py`
  * `legacy_scripts/add_metadata-v3.4.py`
  * `legacy_scripts/convert_md_to_pdfs-v3.6.py`
  * `legacy_scripts/check_missing_pdfs-v1.6.sh`
  * `legacy_scripts/secret_export_gemini_api_key-v1.4.sh`

---

## 7. legacy_scripts を FastAPI に移植する際のAPI仕様

### A. 目的と互換方針
* 既存の `oneshot_pipeline` を **API 1回呼び出しで同等の成果物**（Markdown、PDF）に変換できること。 
* **DOCX生成は実装しない。** 
* 既存スクリプトの処理順と出力ディレクトリ構造を維持し、差分検証が容易な形で移植する。
* APIキーは `multipart/form-data` の `api_key` を優先し、未指定時のみ `GEMINI_API_KEY` を参照する。

### B. 推奨エンドポイント（Pipeline型）
1. **解説生成パイプライン開始**
   * **URL**: `POST /api/v1/pipeline`
   * **Content-Type**: `multipart/form-data`
   * **Parameters (Form Data)**:
     * `api_key` (String, optional) - Gemini API Key（未指定時は環境変数フォールバック）
     * `input_file` (File, required) - PDF/JPEG/PNG 20MBまで
     * `explanation_name` (String, required) - 生成する解説の名称
     * `university` (String, required) - 大学名 (例: 東京大学)
     * `year` (String, required) - 年度 (例: 2024)
     * `subject` (String, required) - 科目名 (例: 生化学)
     * `author` (String, required) - 作成者名 (例: 佐藤先生)
   * **Response**: `202 Accepted`
   ```json
   {
     "status": "accepted",
     "job_id": "pipeline-20251210-001234",
     "message": "パイプラインを開始しました。完了後にダウンロードしてください。"
   }
   ```

2. **処理状況確認**
   * **URL**: `GET /api/v1/pipeline/{job_id}`
   * **Response**:
     * `200 OK`（完了）
     * `202 Accepted`（処理中）
     * `404/410`（不在/期限切れ）

3. **成果物ダウンロード**
   * **URL**: `GET /api/v1/pipeline/{job_id}/download`
   * **Response**:
     * `200 OK` + PDF

### C. 推奨エンドポイント（ステップ単体・デバッグ用、必要なら）
* `POST /api/v1/pipeline/generate_markdown`  
  入力ファイル → Markdown を生成。`generate_answer_md-v2.2.py` 相当。
* `POST /api/v1/pipeline/convert_markdown`  
  Markdown → PDF。`convert_md_to_pdfs-v3.6.py` 相当（DOCX/脚注付きMarkdownは無効）。

### D. 入力変換ポリシー
* 画像入力（JPEG/PNG）は **PDF化して Gemini に送信** する。
* 生成物は `data/outputs/{job_id}/markdown` と `metadata.json` を保存する。
* PDF はパイプライン内で生成し、`data/outputs/{job_id}/` に `explanation_name.pdf` で保存する。
* PDF は生成後 **永久に保存**する。

---

## 8. legacy_scripts 移植の実装計画（FastAPI）

実装完了。仕様変更時は `app/services/legacy/` と `main.py` を更新する。
