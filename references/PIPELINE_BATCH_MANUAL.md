以下は、**手元で安定運用するためのマニュアル（Markdown ファイル）**としてそのまま保存できる内容です。
（例：PIPELINE_BATCH_MANUAL.md という名前で保存してください）

⸻


# FastAPI Pipeline 一括実行・ダウンロード運用マニュアル

本書は、  
**指定フォルダ内の PDF ファイルを一括で FastAPI Pipeline に投入し、  
一定時間後に生成結果（ZIP）をダウンロードするための運用マニュアル**です。

- リクエスト（POST）とダウンロード（GET）を **完全に分離**
- 長時間処理（約15分）を前提に、**安定的・再実行可能**な構成
- 将来忘れたときに **思い出せること** を目的としています

---

## 全体構成

.
├── pipeline_request_all.sh    # PDFを一括でAPIに送信（job_id生成）
├── pipeline_download_all.sh   # job_idを元にZIPを一括ダウンロード
├── job_ids.csv                # job_idの一覧（中間生成物）
└── PIPELINE_BATCH_MANUAL.md   # ← このマニュアル

---

## 処理フロー概要

1. **PDFフォルダを指定してリクエスト実行**
   - 各PDF → API POST
   - レスポンスから `job_id` を取得
   - `job_ids.csv` に記録

2. **一定時間待機（例：15分）**

3. **job_ids.csv を元にダウンロード実行**
   - `GET /api/v1/pipeline/{job_id}/download`
   - ZIP を `~/Downloads` に保存

---

## 必要な環境

### OS
- macOS（zsh / bash）
- Linux（bash）

### 必須コマンド
- `curl`
- `python3`
- `grep`
- `head`

macOS 標準環境でほぼ満たされます。

### Python
```sh
python3 --version
```

※ python コマンドは使用しません（python3 固定）

⸻

事前準備

1. API_KEY の設定（必須）

export API_KEY="AIzaSyxxxxxxxxxxxxxxxxxxxx"

.zshrc や .bashrc に書いても可

⸻

2. スクリプトに実行権限を付与

chmod +x pipeline_request_all.sh
chmod +x pipeline_download_all.sh


⸻

スクリプト①：リクエスト用

pipeline_request_all.sh

役割
	•	指定フォルダ内の 全PDFを API に送信
	•	ファイル名から 年号（4桁）を自動抽出
	•	各リクエストの job_id を CSV に保存

内部で行っていること（概要）
	•	対象：TARGET_DIR/*.pdf
	•	抽出項目：
	•	input_file → PDF 本体
	•	explanation_name → ファイル名（basename）
	•	year → ファイル名中の最初の4桁
	•	出力：
	•	job_ids.csv

実行方法

./pipeline_request_all.sh "/Users/embryo03/Documents/medteria/PoC-神戸大学-3回生/PoC-神戸大学-3年_3-2-7_精神科"

出力例（標準出力）

=== REQUEST: 2021年度 精神科_小テスト.pdf
JOB_ID=pipeline-xxxx
=== REQUEST: 2022年度 精神科_小テスト.pdf
JOB_ID=pipeline-yyyy

出力ファイル：job_ids.csv

pdf_path,basename,year,job_id
".../2021年度 精神科_小テスト.pdf","2021年度 精神科_小テスト.pdf","2021","pipeline-xxxx"

この CSV が 次のダウンロード工程の入力になります

⸻

スクリプト②：ダウンロード用

pipeline_download_all.sh

役割
	•	job_ids.csv を読み込み
	•	各 job_id に対して

GET /api/v1/pipeline/{job_id}/download


	•	ZIP ファイルを ~/Downloads に保存

特徴
	•	curl -OJ を使用
	•	サーバーの Content-Disposition を尊重
	•	ファイル名を自動決定
	•	zip / pdf の拡張子指定不要

実行方法

./pipeline_download_all.sh ./job_ids.csv

保存先

/Users/embryo03/Downloads/
├── pipeline-xxxx.zip
├── pipeline-yyyy.zip
└── ...


⸻

運用上の注意点

1. リクエストとダウンロードは必ず分離
	•	API処理は 即完了しない
	•	同一スクリプトで連続実行しないこと

2. 途中失敗しても問題なし
	•	job_ids.csv が残る
	•	ダウンロードは 何度でも再実行可能

3. ファイル名に空白があってもOK
	•	全て "..." でクォート済み

⸻

よくあるトラブルと対処

Q. zsh: command not found: -F

原因
	•	for ...; do; echo ...; JOB_ID=$(curl ... のような
1行ベタ書き

対策
	•	本マニュアルのように スクリプトファイル化

⸻

Q. python: command not found

原因
	•	macOS では python が存在しない

対策
	•	常に python3 を使用（本スクリプトは対応済）

⸻

Q. 年号が取れず SKIP される

原因
	•	ファイル名に4桁数字が含まれていない

対策
	•	ファイル名規約を統一
例：2023年度_XXXX.pdf

⸻

カスタマイズポイント（将来用）
	•	UNIVERSITY / SUBJECT / AUTHOR の変更
	•	TARGET_DIR を再帰探索に変更
	•	CSV に開始時刻・終了時刻・HTTP status を追加
	•	並列実行（※ API負荷注意）
