#!/usr/bin/env bash
set -euo pipefail

Missing_files=()
SOURCE_DIR="PoC-grade2"

# /PoC-grade2 配下の PDF を列挙（グロブは使わず find で安全に）
find "${SOURCE_DIR}" -type f \( -name "*.pdf" -o -name "*.docx" \) -print0 | while IFS= read -r -d '' src; do
  stem="$(basename "${src%.*}")"
  # 出力側に「stem を含む *.pdf」が一つでもあればヒット
  if ! find output-runPipelinePy/pdf -type f -name "*${stem}*.pdf" -print -quit | grep -q .; then
    echo "MISSING: ${src}"
    Missing_files+=("${src}")
  fi
done

echo "Total missing files: ${#Missing_files[@]}"
echo "Next steps:"
echo "for missing_file in ...";
# echo """
# for missing_file in "${Missing_files[@]}"; do
#     echo "Processing: ${missing_file}";
#     python3.11 run_pipeline.py "${missing_file}";
#     echo ""
# done
# """

# 変更履歴
# ver1.6 - PDFだけでなく、.docxも考慮するように変更
# ver1.4 - 次のステップの例を表示するように追加
# ver1.3 - 出力にソースディレクトリを含めるように変更
# ver1.2 - 変更をもとに戻した。変数に格納した方がいいと判断した。