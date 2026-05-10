# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 概要

日本語縦書き・見開きPDFをGemini APIでテキスト化するOCRツール。Web版（`index.html`、ブラウザのみで動作）とCLI版（`gemini_ocr_v2.py`）の2形態がある。

## セットアップ・実行

```bash
# 依存パッケージのインストール
pip install -r requirements.txt

# .env にAPIキーを設定
echo "GEMINI_API_KEY=your_key_here" > .env

# CLI実行（基本）
python gemini_ocr_v2.py path/to/your.pdf

# 無料枠ユーザー（15 RPM / 3並列）
python gemini_ocr_v2.py path/to/your.pdf --free

# ページ範囲指定・レイアウト強制
python gemini_ocr_v2.py path/to/your.pdf --start 3 --end 10 --single
python gemini_ocr_v2.py path/to/your.pdf --spread
```

出力は入力PDFと同ディレクトリに `{stem}_ocr_v2.txt` として保存される。

テスト用スクリプトは `tests/` 配下にあるが、正式なテストフレームワークは使用していない（アドホックなデバッグ用）。

## アーキテクチャ

### 処理パイプライン（CLI版）

```
gemini_ocr_v2.py (エントリポイント)
    └── OCROrchestrator.run()
            ├── 1. _prepare_processing_units() ── PDF→JPEG変換 → レイアウト判定 → ProcessingUnit生成
            ├── 2. GeminiExtractor.extract_text() ── 逐次実行、前ページの末尾300文字を文脈として引き継ぎ
            └── 3. ResultConstructor.construct() ── OCRResultをページグループ単位でファイル出力
```

### データモデル（`models.py`）

- **`OCRConfig`**: 実行設定（frozen dataclass）。`from_args()` でCLI引数から生成。`--free` フラグで `concurrency=3, rpm_limit=15` に切り替わる。
- **`ProcessingUnit`**: 処理単位（画像1枚）。`prev_context`（前ページ末尾テキスト）を持ち、Geminiプロンプトに埋め込む。
- **`OCRResult`**: API呼び出し結果。`status` は `PENDING/OK/ERROR/RETRY_FAILED` のいずれか。

### `processor/` モジュール

| ファイル | 役割 |
|---|---|
| `ocr_orchestrator.py` | 全工程統括。PDF→画像変換、逐次処理ループ、ファイル出力 |
| `image_detector.py` | 見開き分割（ノド検出）、二段組/一段組判定を画素値解析で実施 |
| `gemini_extractor.py` | Gemini API非同期呼び出し。429エラー時に `TierManager.notify_429()` を呼んでダウンシフト、リトライ最大5回 |
| `tier_manager.py` | シングルトン。`PAID(20並列/2000RPM)` ↔ `FREE(3並列/15RPM)` を動的に切り替え |
| `prompts.py` | OCRプロンプト定数。`OCR_PROMPT_STRUCTURED`（二段組用）と `OCR_PROMPT_RELAXED`（一段組用）の2種 |
| `result_constructor.py` | `is_group_start=True` のユニットでページグループヘッダを挿入し、テキストをフラッシュしながら書き出す |
| `utils.py` | ファイル名サフィックスからサイドラベルと `is_group_start` フラグを返す |

### レイアウト判定ロジック

- **見開き判定**: アスペクト比 > 1.1 → 見開きと判断。中央40〜60%の列輝度でノド（綴じ目）X座標を検出。`is_reliable` が偽の場合は分割せず安全策をとる。
- **二段組判定**: 中央35〜65%行・40〜60%列の輝度最小値が平均の20%未満かつ上下両側に文字密度があれば二段組と判定（閾値 `two_column_threshold=0.2`）。

### Web版（`index.html`）

サーバー不要のスタンドアロンHTML。JavaScriptで同等のレイアウト判定・Gemini API呼び出しを実装。CLI版との機能同期が必要な際は `docs/gemini_ocr/design.md` を参照。

## モデル設定

デフォルトモデルは `gemini-3.1-flash-lite-preview`（`models.py:9`）。`thinking_level="LOW"` で `temperature=0.0` を使用。モデル変更は `OCRConfig.model_id` を修正する。
