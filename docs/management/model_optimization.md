# Model Optimization Guide: Gemini 3 Flash

Gemini 3 Flash は、最先端の知能を圧倒的なスピードと低コストで提供するモデルです。

> **公式ドキュメント**: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-flash?hl=ja
https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-1-flash-lite?hl=ja

## 1. 推奨モデル構成

| 推奨モデル | 理由 | 備考 |
| :--- | :--- | :--- |
| `gemini-3.1-flash-lite-preview` | **500 RPD** (Free tier) / **高速** (~30%減) | `Thinking: High` 必須 |
| `gemini-3-flash-preview` | 応答が極めて安定。1チャンクあたりの推論が重厚。 | **20 RPD** 制限に注意 |

## 2. Thinking Level (思考レベル) の活用

Gemini 3.1 シリーズから導入された `thinking_level` パラメータを制御することで、Lite モデルでも高品質な翻訳・解析が可能です。

- **`HIGH` (高)**: 論理的なステップを細かく実行する。学術論文のレジュメ生成や複雑な構造の翻訳に必須。
- **自動設定**: `llm_client.py` では、モデル名に `gemini-3.1-flash` が含まれる場合に自動で `thinking_level: HIGH` をセットするように実装されています。

### SDK 実装上の注意 (Python)
`google-genai` SDK では、以下のように `thinking_config` のネスト内に配置する必要があります。
```python
config = types.GenerateContentConfig(
    thinking_config = types.ThinkingConfig(thinking_level="HIGH")
)
```

## 3. レート制限 (2026年3月現在)

Google AI Studio の無料枠における RPD (Requests Per Day) の現状：

- **Gemini 1.5 Flash / Pro**: サービス終了または大幅な制限。
- **Gemini 2.0 / 3.0 Flash**: **20 RPD**。
- **Gemini 3.1 Flash Lite**: **500 RPD**。
