# AGENTS.md

## 1. プロジェクト概要

**プロジェクト名**: AI解説生成システム (Prototype)  
**目的**: 過去問解説PDFをAIを用いて自動生成するシステムのAPIプロトタイプ構築。  
**ターゲット**: 2026年2月までのプロトタイプ完成、およびVPS上のAPIとしての稼働。  
**現状フェーズ**: ステップ1〜2（ローカル環境でのAPI構築とテスト、Github共有基盤の整備）。

---

## 2. 技術スタック

- **言語**: Python **3.13.x**
- **Webフレームワーク**: FastAPI  
    - 非同期処理  
    - Swagger UI による動作確認の容易さを重視
- **サーバー**: Uvicorn (ASGI)
- **AI API**: Google Gemini API  
    - **python google-genai SDK を使用**
    - REST API の直接呼び出しは行わない
- **文書変換**:
    - Markdown → DOCX / PDF 変換は **pandoc** を使用
    - Python 側では pandoc を subprocess 経由で呼び出す
- **認証**: Basic認証（プロトタイプ段階）
- **環境管理**:
    - 仮想環境: `minimum-venv`
    - 依存管理: `requirements-min.txt`

---

## 3. 仮想環境・実行環境の方針（重要）

本プロジェクトでは、**再現性と依存トラブル回避を最優先**とし、以下の仮想環境を正式な実行前提とする。

### 仮想環境

- **仮想環境名**: `minimum-venv`
- **Python バージョン**: **Python 3.13.x**
- **作成方法**:
  ```bash
  python3.13 -m venv minimum-venv
  ```
- **有効化**:
  ```bash
  source minimum-venv/bin/activate
  ```

### 運用ルール

- すべての Python スクリプト / FastAPI サーバーは `minimum-venv` 上でのみ実行されることを前提とする
- `python3` / `pip` の直接呼び出しは禁止し、仮想環境内の `python` / `pip` を使用する
- シェルスクリプトは、仮想環境が未有効な場合に自動で `minimum-venv` を `activate` する設計とする

### 依存関係管理

- 依存関係は `requirements-min.txt` に完全固定する
- **作成方法**:
  ```bash
  pip freeze > requirements-min.txt
  ```
- **別環境での再現**:
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
│   ├── auth.py
│   ├── models.py
│   └── services/
│       ├── generator.py     # 解説生成・pandoc呼び出し処理
│       └── file_manager.py
│
├── references/
│   └── (md_files)
│
├── legacy_scripts/          # 既存のワンショット実行スクリプト群
│
└── data/                    # 【Git管理外】
    ├── inputs/
    └── outputs/
```

---

## 5. 開発・運用ルール

### A. 解説生成・PDF化の方針

- 解説本文は Markdown を中間成果物とする
- Markdown 生成は Gemini API（google-genai SDK）で行う
- 最終成果物（DOCX / PDF）は pandoc により生成する
- OS依存・C拡張に強く依存するライブラリ（例: weasyprint）は使用しない

### B. API設計方針（FastAPI）

生成処理は長時間になることが想定されるため、非同期処理を前提とする。

1.  **Request**
    - ファイルアップロードを受け付け、即座に Job ID を返す
2.  **Process**
    - BackgroundTasks により生成処理を実行
3.  **Download**
    - Job ID に基づき、生成済み成果物を取得

### C. セキュリティ・キー管理

- Gemini API Key はコードに直接書かない
- `secret_export_gemini_api_key.sh` により
    - キーのロード
    - google-genai SDK での疎通確認
    - 有効キーの export
を事前に保証する
- FastAPI 側では `os.environ["GEMINI_API_KEY"]` の存在を前提とする

---

## 6. API仕様（v1 Prototype）

### 1. 生成リクエスト

- **URL**: `POST /api/v1/generate_explanation`
- **Content-Type**: `multipart/form-data`
- **Response**: `202 Accepted`
  ```json
  {
    "job_id": "uuid...",
    "status": "accepted"
  }
  ```

### 2. ダウンロード

- **URL**: `GET /api/v1/download_explanation/{job_id}`
- **Response**:
    - **完了**: `200 OK`（ZIP）
    - **処理中**: `202 Accepted`

---

## 7. 今後のVPS移行に向けた留意点

- XServer VPS 等へのデプロイを想定
- ローカルでは以下で起動
  ```bash
  uvicorn main:app --reload
  ```
- 本番では Apache / Nginx 配下での起動を想定し、
    - ポート番号
    - パス
    - ファイル保存先
をハードコードしない

---

## 8. 次の自然なステップ（提案）

次にやると設計が一気に締まります：

1.  **FastAPI用 `app/services/generator.py` の責務整理**
    - 既存ワンショットパイプラインとの対応表
2.  **API用に最低限必要なエンドポイントだけ切り出した設計**
3.  **oneshot → FastAPI BackgroundTasks への移植指針**

どこから詰めるか、指定してください。