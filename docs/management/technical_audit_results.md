# 技術監査結果: gemini_ocr.py (Technical Audit)

## 1. 現状分析
- **ファイルサイズ**: 454行（300行ルールに抵触）
- **責務の混在**:
    - 定数・プロンプト定義（Configuration）
    - 画像解析・レイアウト判定（Heuristics/Logic）
    - PDF処理・ファイル管理（File I/O）
    - Gemini API 通信・リトライ（External Service Logic）
    - CLI 引数パース・実行制御（Orchestration）
- **データ管理**: 基本的に `Path` や `tuple` の受け渡しで完結しており、状態をカプセル化したモデルが存在しない。

## 2. 抽出されたコンポーネント (Submodules)

### A. Data Models (`models.py`)
- `OCRConfig`: ティア、DPI、プロンプト等の設定。
- `ProcessingUnit`: 分割された画像、ラベル、所属ページ等のメタデータ。
- `OCRResult`: 抽出テキスト、トークン使用量、実行時間等の結果。

### B. Image Detector (`processor/image_detector.py`)
- `find_gutter_x`: 見開きの綴じ目（ノド）を検出。
- `LayoutAnalyzer`: 段組（一段組/二段組）の判定と分割。

### C. Gemini Extractor (`processor/gemini_extractor.py`)
- `GeminiClient`: API 通信、リトライ、レート制限の管理。
- プロンプト・テンプレートの管理。

### D. Result Constructor (`processor/result_constructor.py`)
- 抽出された断片テキストの結合。
- キャッシュ管理（将来的な拡張を見据えて）。
- ファイル出力ロジック。

### E. OCR Orchestrator (`processor/ocr_orchestrator.py`)
- PDFから画像への変換。
- 判定、抽出、構築のフロー制御。
- 進捗表示。

## 3. リファクタリングの方針
1. **Model First**: まず `models.py` を作成し、情報の流れを確定させる。
2. **Atomic Logic**: 画像処理と API 通信を純粋な関数/クラスとして独立させる。
3. **Flat Package**: ユーザーの要望「バグ・エラーが少ない方」を考慮し、複雑なパッケージ構成は避け、`processor/` 配下に分かりやすく配置する。
4. **Entry Point**: 元の `gemini_ocr.py` は、引数を受け取って Orchestrator を呼び出すだけの「薄い皮（Launcher）」とする。
