# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

日本語縦書き・見開きPDFをGemini APIでテキスト化するOCRツール。CLI版（`gemini_ocr_v2.py`）とWeb版（`index.html`、ブラウザのみで動作）の2モードを持つ。

## 環境セットアップ

```bash
# 依存パッケージのインストール
pip install -r requirements.txt

# .env にAPIキーを設定
echo "GEMINI_API_KEY=your_key_here" > .env
```

必須環境変数: `GEMINI_API_KEY`（Google Gemini API）。

## よく使うコマンド

```bash
# CLI実行（基本）
python gemini_ocr_v2.py path/to/your.pdf

# 無料枠ユーザー（15 RPM / 3並列）
python gemini_ocr_v2.py path/to/your.pdf --free

# ページ範囲指定・レイアウト強制
python gemini_ocr_v2.py path/to/your.pdf --start 3 --end 10 --single
python gemini_ocr_v2.py path/to/your.pdf --spread

# Web版
# index.html をブラウザで開く（サーバー不要、クライアント側で API キーを入力）
```

出力は入力PDFと同ディレクトリに `{stem}_ocr_v2.txt` として保存される（CLI版）。

テスト用スクリプトは `tests/` 配下にあるが、正式なテストフレームワークは使用していない（アドホックなデバッグ用）。

## アーキテクチャ

### 処理パイプライン

```
CLI版: gemini_ocr_v2.py (エントリポイント)
    └── OCROrchestrator.run()
            ├── 1. _prepare_processing_units() ── PDF→JPEG変換 → レイアウト判定 → ProcessingUnit生成
            ├── 2. GeminiExtractor.extract_text() ── 逐次実行、前ページの末尾300文字を文脈として引き継ぎ
            └── 3. ResultConstructor.construct() ── OCRResultをページグループ単位でファイル出力

Web版: index.html
    └── JavaScript で同等のレイアウト判定・Gemini API 呼び出し（クライアント側で API キー管理）
```

### CLI版とWeb版の機能対応

- **CLI版（`gemini_ocr_v2.py`）**: バッチ処理、並列度制御（FREE/PAID）、大規模PDF向け
- **Web版（`index.html`）**: ブラウザベース、インタラクティブ、サーバー不要。JavaScriptで同等のレイアウト判定・Gemini API呼び出しを実装

### データモデル（`models.py`）

- **`OCRConfig`**: 実行設定（frozen dataclass）。`from_args()` でCLI引数から生成。`--free` フラグで `concurrency=3, rpm_limit=15` に切り替わる。
- **`ProcessingUnit`**: 処理単位（画像1枚）。`prev_context`（前ページ末尾テキスト）を持ち、Geminiプロンプトに埋め込む。
- **`OCRResult`**: API呼び出し結果。`status` は `PENDING/OK/ERROR/RETRY_FAILED` のいずれか。

### `processor/` モジュール

| ファイル | 役割 |
|---|---|
| `ocr_orchestrator.py` | 全工程統括。PDF→画像変換、逐次処理ループ、ファイル出力 |
| `image_detector.py` | 見開き分割（ノド検出）、二段組/一段組判定を画素値解析で実施 |
| `gemini_extractor.py` | Gemini API非同期呼び出し。429エラー時、まず `ModelRotator` によるモデル切替を試み、プール枯渇後に `TierManager.notify_429()` でダウンシフト。リトライ最大5回 |
| `tier_manager.py` | シングルトン。`PAID(20並列/2000RPM)` ↔ `FREE(3並列/15RPM)` を動的に切り替え |
| `model_rotator.py` | シングルトン。無料枠Liteプール（`gemini-3.1-flash-lite`/`gemini-3.5-flash-lite`、RPM/RPD完全一致・カウンタ独立）内でforward-onlyローテーションし、無料枠の実質容量を拡張。既定で常時有効 |
| `prompts.py` | OCRプロンプト定数。`OCR_PROMPT_STRUCTURED`（二段組用）と `OCR_PROMPT_RELAXED`（一段組用）の2種 |
| `result_constructor.py` | `is_group_start=True` のユニットでページグループヘッダを挿入し、テキストをフラッシュしながら書き出す |
| `utils.py` | ファイル名サフィックスからサイドラベルと `is_group_start` フラグを返す |

### レイアウト判定ロジック

- **見開き判定**: アスペクト比 > 1.1 → 見開きと判断。中央40〜60%の列輝度でノド（綴じ目）X座標を検出。`is_reliable` が偽の場合は分割せず安全策をとる。
- **二段組判定**: 中央35〜65%行・40〜60%列の輝度最小値が平均の20%未満かつ上下両側に文字密度があれば二段組と判定（閾値 `two_column_threshold=0.2`）。

## モデル設定・最適化

- **Gemini API 共通知識**（モデル一覧・thinking_level・無料枠・廃止情報）は `docs/gemini_models.md` を参照。これは `~/Code/shared/gemini_models.md` から同期された共通ドキュメント（直接編集禁止）。
- **デフォルトモデル**: `gemini-3.1-flash-lite`（`models.py:9`、GA版）。旧`-preview`版は2026-05-25にシャットダウン済みで、既にGA版へ移行完了している。
- **推論設定**: `thinking_level="LOW"`, `temperature=0.0`
- **真実ソース**: `models.py` の `OCRConfig.model_id` が正本。変更後はプロセス再起動が必要
- **モデル変更の手順**: `models.py` の `DEFAULT_MODEL` を更新し、両 CLI 版・Web 版で動作確認
- **無料枠2モデル併用**（`--free` 時、`docs/management/model_optimization.md` §5 に詳細）:
  - `ModelRotator`（容量2倍化）は既定で常時有効。429検知時、ダウンシフトより優先してもう一方のLiteモデルへ自動切替。リスクなし。
  - `--parallel-pool`（速度改善、ページペア単位ラウンドロビン）は**既定OFF・非推奨**。実測で約30%高速化するが、ペア内でユニットが1ページ古い文脈を共有する構造上、段落の重複・欠落や誤字が実地検証で確認されている。精度優先の通常利用では使わないこと。
