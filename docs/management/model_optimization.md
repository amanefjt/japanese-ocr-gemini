# Model Optimization Guide: Gemini 3 Flash

Gemini 3 Flash は、最先端の知能を圧倒的なスピードと低コストで提供するモデルです。

> **公式ドキュメント**: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-flash?hl=ja

## Model Specifications
- **Model Name**: `gemini-3-flash-preview`
- **Max Input Tokens**: **1,048,576** (1M)
- **Max Output Tokens**: **65,536** (65k tokens)
- **Thinking Mode**: 対応。`thinking_level` パラメータ（MINIMAL / LOW / MEDIUM / HIGH）で推論量を制御可能。Gemini 3 では `thinking_budget` に名称変更。
- **Media Resolution**: `media_resolution` パラメータ（低/中/高/超高）でマルチモーダル入力の処理精度を制御可能。
- **Performance**:
    - **GPQA Diamond**: 90.4% (博士レベルの推論能力)
    - **SWE-bench Verified**: 78% (Gemini 3 Pro を上回るコーディング性能)
    - **Speed**: Gemini 2.5 Pro の **3倍の処理速度** を実現。
    - **Cost**: 入力 $0.50 / 1M tokens, 出力 $3.00 / 1M tokens (極めて低コスト)。

## コード上の設定
- `src/llm_processor.py`: `max_output_tokens=65536` で既にモデルの物理上限に設定済み。
- これ以上の出力トークン増加はモデル仕様上不可能。

## Optimization Strategy
Gemini 3 Flash の出力トークン制限 (65k tokens) は、理論上は**日本語テキストで約20,000〜30,000文字**程度まで一気に出力可能です。

### Practical Limits (Battle-Tested)
実戦においては、以下の理由から理論値よりも低いしきい値を採用しています：
- **タスクの重さ**: 「一字一句漏らさぬ転写 ＋ OCRノイズ除去 ＋ 構造化」という複合タスクでは、AI の内部的な推論負荷（トークン消費）が高まり、理論限界に達する前にスタミナ切れ（出力停止）を起こす傾向がある。


