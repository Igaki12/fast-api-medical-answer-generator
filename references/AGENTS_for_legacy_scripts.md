# AGENTS Playbook

メドテリアの過去問処理パイプラインを手動・半手動で回す際のガイドです。Codex 等のエージェントが状況をすばやく把握し、既存パイプラインと同じ成果物を再現できるようにまとめています。

## 0. パイプライン全体像

標準の一括処理は `oneshot_pipeline.sh` が司令塔になります。入力 PDF ごとに以下の工程を順番に実施し、最終的に DOCX/PDF/脚注付き Markdown を生成して指定の出力ディレクトリへ配置します。

1. 出力ディレクトリの初期化（`<OUTPUT>/markdown` を作成）
2. `secret_export_gemini_api_key.sh` の実行で Gemini API キーを `GEMINI_API_KEY` / `GOOGLE_API_KEY` としてエクスポート
3. `check_missing_files.sh <INPUT_DIR> <OUTPUT_DIR>` で未処理 PDF リストを作成（`missing_list.txt`）
4. `missing_list.txt` を 1 行ずつ処理  
   a. `generate_answer_md.py <pdf_path> <OUTPUT>/markdown` … Markdown 解答を生成  
   b. `add_metadata.py <OUTPUT>/markdown/<stem>_解答解説.md` … メタデータ YAML を作成  
   c. `convert_md_to_pdfs.py <OUTPUT>/markdown/<stem>_解答解説.md` … DOCX/PDF と脚注入り Markdown を作成  
5. `markdown/markdown_with_attrib` を `<OUTPUT>/markdown_with_attrib` に移動して完了

`oneshot_pipeline.sh` や補助スクリプト群はすべてプロジェクト直下の `minimum-venv`（Python 3.13）を自動で activate し、その venv の Python で処理を行います。手動再現時も同じ venv を使ってください。

## 1. 主要スクリプト（最新版）

拡張子の後ろ（例: `-v1.3`）付きのファイルは旧版です。**末尾にバージョン番号が無いファイルが常に最新です**。自動・手動を問わず、基本的にこちらを利用してください。

| 役割 | 最新スクリプト | 備考 |
| --- | --- | --- |
| パイプライン本体 | `oneshot_pipeline.sh` | 引数: `<INPUT_DIR> <OUTPUT_DIR> [MISSING_LIST_PATH]`。`minimum-venv` を自動 activate し、SCRIPT_DIR 基準で各スクリプトを venv Python から順番実行（missing_list を読み込みつつ 1 件ずつ Markdown→メタデータ→DOCX/PDF）。 |
| 未処理 PDF 抽出 | `check_missing_files.sh` | `minimum-venv` で動作。入力ディレクトリ内の PDF/DOC/DOCX/JPEG/PNG/TIFF を走査し、`OUTPUT_DIR` 配下に stem を含む PDF が無いものを抽出。`MISSING_LIST_PATH` 環境変数を指定するとリストをファイル書き出し（SCRIPT_DIR 基準で解決）。 |
| 解答 Markdown 生成 | `generate_answer_md.py` | Gemini API を利用して過去問→解答解説 Markdown を出力 |
| メタデータ生成 | `add_metadata.py` | YAML サイドカーを `<OUTPUT>/metadata-yaml` に作成。`GOOGLE_API_KEY` または `GEMINI_API_KEY` が必要 |
| DOCX/PDF 変換 | `convert_md_to_pdfs.py` | pandoc + LuaLaTeX 専用。サイドカーYAMLまたは `BLOCKQUOTE_ATTRIBUTION` 環境変数から引用脚注を生成し、`markdown_with_attrib` の脚注付 Markdown も作成。 |
| API キー設定 | `secret_export_gemini_api_key.sh` | `minimum-venv` の Python で google-genai SDK を使って `gemini-3-pro-preview` へ疎通確認し、`gemini_api_keys.txt` から最初に成功したキーを `GEMINI_API_KEY` として export（`GOOGLE_API_KEY` は自動設定されません）。 |

## 2. 依存ソフトウェアと環境変数

- **Python（minimum-venv / 3.13）**: すべての Bash/Python スクリプトは `minimum-venv` 前提。`oneshot_pipeline.sh` と `secret_export_gemini_api_key.sh` / `check_missing_files.sh` が自動で activate するが、手動実行時は `source minimum-venv/bin/activate` を忘れずに。`requirements.txt` 相当のライブラリ（`google-genai`, `PyYAML` など）を venv に入れておく。  
- **Gemini API**: `secret_export_gemini_api_key.sh` が `gemini_api_keys.txt` の候補を google-genai SDK 経由で検証し、使えるキーを `GEMINI_API_KEY` として export する。`generate_answer_md.py` / `add_metadata.py` は `GOOGLE_API_KEY` → `GEMINI_API_KEY` の順で参照するため、通常はスクリプトを source するだけで十分。必要があれば `export GOOGLE_API_KEY="$GEMINI_API_KEY"` を追加。  
- **pandoc + LuaLaTeX**: `convert_md_to_pdfs.py` は常に pandoc + LuaLaTeX を使用して DOCX/PDF を生成し、引用脚注用の Markdown （`markdown_with_attrib`）も同時作成する。`header-lua.tex`, `header-quote-bg.tex` などのカスタムヘッダをプロジェクト直下に置き、同じディレクトリから実行する。  
- **LibreOffice**（オプション）: 旧バージョンのパイプラインで DOCX→PDF の変換に利用していた履歴あり。最新では pandoc+LuaLaTeX がメイン。

## 3. 出力ディレクトリ構成

標準的な処理の結果、`<OUTPUT_DIR>` は以下の構造になります（手動処理でも同じ配置に揃えること）。

```
<OUTPUT_DIR>/
  markdown/                     # 元のMD
  metadata-yaml/                # サイドカーYAML
  docx/                         # pandoc生成のWordファイル
  pdf/                          # pandoc生成のPDF
  markdown_with_attrib/         # 引用脚注と注意書きを追記したMD
  .pandoc-tmp/                  # convert_md_to_pdfs.py が生成する一時ディレクトリ
```

`convert_md_to_pdfs.py` が `markdown/markdown_with_attrib` に脚注付き Markdown を保存するため、処理後に oneshot パイプラインでは自動で `<OUTPUT_DIR>/markdown_with_attrib` へ移動します。手動で実行する際もこの移動を忘れないこと。

## 4. 手動で再現する場合の手順

トラブル時に手動でパイプラインを再現する場合は、以下の順でコマンドを実行すると、oneshot パイプラインと同じ生成物になります。`<OUTPUT_DIR>` 値はケースに合わせて置き換えます。
`python3` は使わず、`minimum-venv` を activate した上で `python` を使ってください。

```bash
source minimum-venv/bin/activate
source secret_export_gemini_api_key.sh
# add_metadata.py は GOOGLE_API_KEY -> GEMINI_API_KEY の順で参照（必要なら手動でエクスポート）
export GOOGLE_API_KEY="$GEMINI_API_KEY"
python generate_answer_md.py "<PDF_PATH>" "<OUTPUT_DIR>/markdown"
python add_metadata.py "<OUTPUT_DIR>/markdown/<stem>_解答解説.md"
python convert_md_to_pdfs.py "<OUTPUT_DIR>/markdown/<stem>_解答解説.md"
mv "<OUTPUT_DIR>/markdown/markdown_with_attrib" "<OUTPUT_DIR>/markdown_with_attrib"
```

複数ファイル（または手動で作成した Markdown）をまとめて処理したい場合は `convert_md_to_pdfs.py` にディレクトリを指定すれば一括で DOCX/PDF を生成できます。

## 5. よくある手動対応の例

- **Markdown を手動編集または新規作成した場合**  
  Markdown を `<OUTPUT_DIR>/markdown` に配置 → `add_metadata.py` → `convert_md_to_pdfs.py` → `markdown_with_attrib` の移動。  
  元 Markdown は必ず残しておき、追加で作った派生ファイル（脚注付きなど）を配置する。

- **分割ファイルを統合して 1 つの PDF にしたい場合**  
  分割 Markdown を結合し、`<OUTPUT_DIR>/markdown/` に新規ファイルを置く。手順 4 に沿ってメタデータ・PDF を再生成する。既存の分割ファイルは削除せず残す。

- **API キーが無効／失敗する場合**  
  `secret_export_gemini_api_key.sh` を単体で実行して成功したキーを確認。ログにマスク表示されたキー末尾が出るので、それを環境変数に固定する。  
  それでも失敗する場合は `GOOGLE_API_KEY` / `GEMINI_API_KEY` を直接エクスポートしてから各 Python スクリプトを走らせる。

## 6. 関連ファイルの所在

| ファイル | 用途 |
| --- | --- |
| `oneshot_pipeline.sh` | 代表的なワンショットパイプライン |
| `generate_answer_md.py` | Gemini で Markdown 解答生成 |
| `add_metadata.py` | Gemini で YAML メタデータ生成 |
| `convert_md_to_pdfs.py` | pandoc で DOCX/PDF 生成、脚注付き Markdown 作成 |
| `check_missing_files.sh` | 入力 PDF と出力済みファイルを比較して未処理リスト作成 |
| `secret_export_gemini_api_key.sh` | 複数の Gemini API キーを試して環境変数に設定 |
| `gemini_api_keys.txt` | `secret_export_gemini_api_key.sh` が参照するキー候補リスト。**APIキーが平文で入るため Git にはコミットせず .gitignore 登録の上、権限管理された環境でのみ保管すること。** |
| `requirements-min.txt` | `minimum-venv` を最小構成で再構築する際の Python 依存パッケージ一覧。`pip install -r requirements-min.txt` を想定。 |
| `header-lua.tex`, `header-quote-bg.tex` | pandoc/LuaLaTeX 変換で読み込む共通ヘッダ。PDF 出力のレイアウト（文書クラス、引用背景）を制御するため、`convert_md_to_pdfs.py` と同じディレクトリに配置しておく。 |
| `run_pipeline.py` | Python 版の総合パイプライン（CLI） |

各ファイルの旧バージョン（`*-v1.6.py` のような命名）は参照用です。更新の際は **バージョン無しファイルを編集** し、必要なら旧版をバックアップとして別名で残す、という運用を守ること。

## 7. 追記・メモ

- `pyenv: cannot rehash: ...` という警告は実行時に表示されることがありますが処理自体には影響しません。
- `convert_md_to_pdfs.py` は `markdown` ディレクトリ配下に一時的な `markdown_sanitized` や `markdown_with_attrib` を作ります。不要になった場合は手動で整理してください。
- `.pandoc-tmp` は一時フォルダです。PDF 生成後に削除しても問題ありませんが、再実行時に自動再生成されます。
- 手動対応後は、成果物のレイアウトや脚注が期待通りかどうか、DOCX/PDF を必ず目視確認してください。

## 8. Python 仮想環境メモ

Python ライブラリを安定運用したい場合は、`AGENTS_for_python_venv_setup.md` に仮想環境（venv）構築手順や推奨設定をまとめています。パッケージ導入や環境差異を吸収する際は必ず参照してください。

必要な情報が足りない場合は、`oneshot_pipeline.sh` を冒頭から読み、どのサブコマンドが呼ばれているかを都度追いながら補足すると、最新の実装に追随できます。
