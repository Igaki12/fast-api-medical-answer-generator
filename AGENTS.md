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
* Markdown → DOCX / PDF 変換は **pandoc** を使用
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
│       ├── generator.py     # Gemini呼び出し・解説生成処理
│       └── file_manager.py  # アップロード/成果物管理
│
├── references/
│   └── (md_files)
│
├── legacy_scripts/          # 既存のワンショット実行スクリプト群
│
└── data/                    # 【Git管理外】
    ├── inputs/              # アップロードされた過去問ファイル(PDF/IMG)
    └── outputs/             # 生成された解説(ZIP/PDF)

```

---

## 5. 開発・運用ルール

### A. 解説生成・マルチモーダル入力

* **入力**: PDF, JPEG, PNG ファイルをサポート（Wordは変換コスト回避のためステップ2では非対応）。
* **中間処理**: 解説本文は Markdown として生成する。
* **出力**: 最終成果物（DOCX / PDF）は pandoc により生成する。
* **AIモデル**: Gemini 3 Pro のマルチモーダル機能 (`inlineData`等) を使用して、画像を直接APIへ渡す。

### B. API設計方針（FastAPI）

生成処理は長時間になることが想定されるため、非同期処理（Job Queue方式）を採用する。これによりHTTPタイムアウトを回避する。

1. **Request**: ファイルとメタデータを受け付け、即座に `Job ID` を返す。
2. **Process**: FastAPIの `BackgroundTasks` によりバックグラウンドで生成を実行。
3. **Download**: クライアントは `Job ID` を使ってポーリングを行い、完了次第成果物（ZIP）を取得する。

### C. セキュリティ・キー管理

* **API Key**: プロトタイプ段階では柔軟性を高めるため、**リクエストボディ (`multipart/form-data`) 内での `api_key` 送信**をサポートする。
* ※サーバー側の環境変数 `os.environ["GEMINI_API_KEY"]` はフォールバックまたは開発用デフォルトとして保持するが、リクエストパラメータを優先する。



---

## 6. API仕様（v1 Prototype）

### 共通事項

* **認証**: Basic Auth
* **プロトコル**: HTTPS (本番/VPS環境)

### 1. 解説生成リクエスト (POST)

* **URL**: `POST /api/v1/generate_explanation`
* **Content-Type**: `multipart/form-data`
* **概要**: 過去問ファイルをアップロードし、生成ジョブを開始する。

**Parameters (Form Data):**

| フィールド名 | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| `api_key` | String | YES | Gemini API Key (クライアント提供) |
| `explanation_name` | String | YES | 生成する解説のタイトル (例: 2025年度 東大物理) |
| `year` | String | YES | 年度 (例: 2024) |
| `university` | String | YES | 大学名 (例: 東京大学) |
| `subject` | String | YES | 科目名 (例: 生化学) |
| `author` | String | YES | 作成者名 (例: 佐藤先生) |
| `input_file` | File | YES | 問題ファイル (PDF/JPEG/PNG) |

**Response:**

* **Status**: `202 Accepted`

```json
{
  "status": "accepted",
  "job_id": "exp-20251210-001234",
  "message": "解説生成リクエストを受け付けました。処理が完了したら、ジョブIDを使って結果をダウンロードしてください。"
}

```

### 2. 解説ダウンロード (GET)

* **URL**: `GET /api/v1/download_explanation/{job_id}`
* **概要**: ジョブIDに基づいて生成状況を確認または成果物をダウンロードする。

**Responseパターン:**

1. **処理完了 (Status 200)**
* **Status**: `200 OK`
* **Header**: `Content-Disposition: attachment; filename="result.zip"`
* **Body**: ZIPファイル（PDF, DOCX, Markdown等を含む）


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




3. **エラー/不在 (Status 404/410)**
* **Status**: `404 Not Found` (ID不一致) または `410 Gone` (有効期限切れ)



---

## 7. 今後のVPS移行に向けた留意点

* XServer VPS 等へのデプロイを想定
* ローカル起動コマンド:
```bash
uvicorn main:app --reload

```


* アップロードファイルの一時保存先や、生成物の保存先は `data/` ディレクトリ配下とし、定期的なクリーンアップ処理（cron等）を今後検討する。

---

## 8. 次のステップ

以下の順序で実装を進めることを推奨します：

1. **Pydanticモデル定義 (`app/models.py`)**
* `multipart/form-data` を受け取るためのフォーム定義作成。


2. **生成ロジックの非同期化 (`app/services/generator.py`)**
* 既存のワンショットスクリプトを関数化し、`api_key` や `file_path` を引数で受け取れるようにリファクタリング。


3. **エンドポイント実装 (`main.py`)**
* `/generate_explanation` と `/download_explanation` の実装。


4. **ローカル動作テスト**
* Swagger UI (`/docs`) または `curl` を用いた画像アップロード・生成テスト。