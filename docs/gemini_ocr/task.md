# タスク: 単一ページ対応とノド検出の堅牢化（安全性優先版）

CLI版 (`gemini_ocr.py`) において、見開きの自動判定と、ノド（綴じ目）が不明瞭な場合の安全策を実装する。

- [x] 現状のコード分析とWeb版ロジックの再確認
- [x] 実装計画の作成とユーザー承認
- [x] `gemini_ocr.py` の修正（安全性優先ロジック）
    - [x] アスペクト比判定 (1.1)
    - [x] 安全性優先の分割ロジック（is_reliable 重視）
    - [x] `--spread` オプションの追加
- [x] 動作検証 (`ethnopdf.pdf` page 2)
- [x] ドキュメント更新 (`requirements_log.md`, `design.md`)
- [x] Web版 (`index.html`) への改善内容の反映
    - [x] UI に単体ページ/見開き強制モードを追加
    - [x] 解析ロジックにアスペクト比 1.1 基準と、ノド検出の安全性（Reliability）を導入
    - [x] `ethnopdf.pdf` による Web版での動作確認
