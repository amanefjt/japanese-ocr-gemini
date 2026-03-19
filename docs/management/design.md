# 設計方針ドキュメント (design.md)

## 1. ワークスペース構成
Antigravity の標準的なエージェント構成に基づき、以下のディレクトリ構造を採用しています。

- `.agent/`: エージェントの自律性を高めるための定義ファイル。
  - `mission.md`: プロジェクト全体の目的。
  - `rules/`: 制約・規約。
  - `skills/`: 再利用可能な手順書。
- `docs/management/`: プロジェクトの健康状態を維持するための「リビングドキュメント」。
  - `requirements_log.md`: 要望の履歴。
  - `troubleshooting_log.md`: 障害と対策の知見。
  - `task.md`: 実行中のタスク管理。
  - `design.md`: 本ドキュメント。

## 2. 採用技術と意図
- **Python (v3.10+)**: OCR の自動化、画像処理、API 通信に適しているため採用。
- **Google GenAI (Gemini API)**: 特に多峰性（画像認識）に優れ、日本語 OCR の精度が高いため採用。
- **Gemini 3 Flash (`gemini-3-flash-preview`)**: 2026年3月時点の最新モデル。高い推論能力と高速な処理、広範な出力トークン（65k）を活かし、複雑なOCRタスクを効率化。
- **pdf2image (poppler)**: PDF から高精細な画像を生成するために使用。メモリ効率化のため、ディスクキャッシュとジェネレータを併用。

## 4. コアエンジン（自動判定と並列実行）
- **全自動レイアウト解析 (Auto-Detection)**: ページごとに「見開き（左右分割）」か「単一ページ」かをアスペクト比で自動判定。さらに、横長画像であっても中央のノド（隙間）が不鮮明な場合は、文字断裁を防ぐため分割をスキップするセーフティ機能を搭載。
- **並列実行エンジン (Parallel with Order Guarantee)**: 
  - **CLI**: `aiolimiter.AsyncLimiter` と `asyncio.Semaphore` を組み合わせ、ティアごとの流量（RPM/同時実行数）を制御。
  - **Web**: 並列で API を叩きつつ、配列で結果を保護することで、最終的な書き出し順序（ページ順）を常に保証。
- **推論最適化**: `thinking_level: LOW` を標準化。活字書籍の解読において AI の「過剰思考」を抑制し、TTFT (Time To First Token) を劇的に改善。

