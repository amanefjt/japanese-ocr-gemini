# 要件定義ログ (requirements_log.md)

| 日次 | 要望・仕様変更・こだわりポイント | ステータス | 備考 |
| :--- | :--- | :--- | :--- |
| 2026-04-01 | `p2workflowy/golden-rewrite` の洗練された処理（Using-superpowers Skill, PDFパイプライン前半の処理）を参考にする。 | 完了 | .agent/ インフラの導入と gemini_ocr.py のモジュール化を実施。 |
| 2026-04-01 | 大規模な gemini_ocr.py を 300行ルールに基づきモジュール分割する。 | 完了 | processor/ 配下に分割。 |
| 2026-04-01 | Gemini 3.1 Flash-Lite (Sequential V3) をプロジェクト標準モデルに設定。 | 完了 | Input $0.075 の低価格と 500 RPD の恩恵を享受。 |
| 2026-07-22 | p2workflowyの無料枠2モデル併用（`ModelRotator`による容量2倍化＋バッチ単位ラウンドロビンによる速度改善）をgocrに移植できないか検証。 | 完了（一部採用） | `ModelRotator`（容量2倍化、429優先ローテーション）は既定で採用。ページペア単位ラウンドロビン（`--parallel-pool`、速度+31.8%）は実地検証で段落重複・誤字を確認したため既定OFFの実験的機能に留めた。詳細は `docs/management/model_optimization.md` §5。 |
