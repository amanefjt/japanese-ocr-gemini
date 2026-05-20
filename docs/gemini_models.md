# Gemini API モデル情報（共通ドキュメント）

3アプリ（p2workflowy / eiyaku / OCR）で共有する Gemini API の最新モデル知見・運用ノウハウ。

- **正本の場所**: `~/Code/shared/gemini_models.md`
- **同期**: `~/Code/shared/sync.sh` を実行すると各 repo の `docs/gemini_models.md` に上書きコピーされる
- **最終更新**: 2026-05-21（Google AI for Developers の公式 changelog および models ページに基づく）

> [!IMPORTANT]
> このファイルは正本（`~/Code/shared/gemini_models.md`）から sync されたコピーです。**直接編集禁止**。修正は正本側で行い、`~/Code/shared/sync.sh` を実行してください。

---

## 1. 現行モデル一覧（2026-05-21 時点）

Google AI Studio で利用可能な主要 API モデル ID。GA = Generally Available（安定版）、Preview = 廃止リスクあり。

### テキスト・マルチモーダル（VLM 含む）

| モデル ID | ステータス | 用途 | 備考 |
|---|---|---|---|
| `gemini-3.5-flash` | **GA**（2026-05-19 GA化） | 最新の Flash。エージェント・コーディング系で「Sustained frontier performance」を目指す新世代 | I/O 2026 で発表 |
| `gemini-3.1-pro-preview` | Preview | 現行フラグシップ Pro。複雑推論・エージェント | 2M トークン context |
| `gemini-3-flash-preview` | Preview | フロンティア性能を低コストで提供する Flash | 2026-01 から提供 |
| `gemini-3.1-flash-lite` | **GA**（2026-05-07 GA化） | 軽量・低コスト・高 RPM。バッチ処理や VLM-OCR の主力 | 旧 `-preview` は 2026-05-25 シャットダウン |
| `gemini-2.5-pro` | GA | 旧世代 Pro。レガシー互換用途 | 新規採用は非推奨 |
| `gemini-2.5-flash` | GA | 旧世代 Flash | 新規採用は非推奨 |
| `gemini-2.5-flash-lite` | GA | 旧世代 Lite | 新規採用は非推奨 |

### 特殊用途

| モデル ID | ステータス | 用途 |
|---|---|---|
| `gemini-3.1-flash-live-preview` | Preview | リアルタイム音声対話 |
| `gemini-3.1-flash-tts-preview` | Preview | TTS（音声合成） |
| `gemini-embedding-2` | GA | マルチモーダル埋め込み |
| `nano-banana-2` / `nano-banana-pro` | Preview | 画像生成 |
| `imagen-4` | GA | テキスト→画像（最大 2K） |
| `veo-3.1-generate-preview` | Preview | 動画生成 |

### 直近のシャットダウン予定（注意）

| モデル ID | 廃止日 | 代替 |
|---|---|---|
| `gemini-3.1-flash-lite-preview` | **2026-05-25** | `gemini-3.1-flash-lite`（GA） |
| `gemini-2.0-flash` 系 | 2026-06-01 | `gemini-3-flash-preview` または `gemini-3.5-flash` |
| `gemini-3-pro-preview` | 2026-03-09（既に shut down） | `gemini-3.1-pro-preview` にリダイレクト |

> [!WARNING]
> `-preview` 付きモデルは予告なく仕様変更・廃止される。本番運用では GA モデルへの移行を推奨。

---

## 2. モデル選定の方針

### 用途別の標準推奨

| 用途 | 推奨モデル | 理由 |
|---|---|---|
| 高品質テキスト生成（翻訳・要約・構造解析） | `gemini-3-flash-preview` または `gemini-3.5-flash` | フロンティア性能 vs コスト。GA 化済みの 3.5-flash が今後の本命 |
| 大量バッチ・低コスト処理（VLM OCR・前処理） | `gemini-3.1-flash-lite` | GA。RPD・RPM が緩く、コストも 1/2 |
| 複雑推論・エージェント | `gemini-3.1-pro-preview` | 2M context、Deep Think Mini 対応 |
| VLM（画像→テキスト） | `gemini-3.1-flash-lite` | OCR 用途で十分。Flash 系列はマルチモーダル対応 |

### 移行戦略

- **新規プロジェクト**: GA モデル（`gemini-3.5-flash` / `gemini-3.1-flash-lite`）を第一候補
- **既存プロジェクト**: `-preview` 利用箇所は changelog を月次で確認し、廃止日の 2 週間前までに GA 版へ切り替える

---

## 3. thinking_level の仕様

Gemini 3 系では `thinking_budget`（数値）から `thinking_level`（列挙値）へ変更された。

### 利用可能な値

| 値 | 想定レスポンス時間 | 用途 |
|---|---|---|
| `LOW` | 1〜3 秒 | 翻訳・分類・OCR など定型処理 |
| `MEDIUM` | 数秒〜十数秒 | 一般的な生成タスク（**2026 年から追加**） |
| `HIGH` | 30 秒以上もあり得る | Deep Think Mini モード。複雑推論・論文要約・構造解析 |

### 重要な仕様

- **デフォルトは `HIGH`**: 明示しない場合は最高コスト・最遅レイテンシ。明示的に指定すべき。
- **課金**: thinking トークンは output トークンと同レートで課金される。
- **適用モデル**: Gemini 3 系列（`gemini-3-*`, `gemini-3.1-*`, `gemini-3.5-*`）。2.5 系列は旧 API（`thinking_budget`）のまま。

### 用途別の推奨設定

| 用途 | thinking_level | 根拠 |
|---|---|---|
| 画像 OCR / VLM | `LOW` | 画像→テキスト変換に思考は不要。コスト最小化 |
| 単純な翻訳・分類 | `LOW` | 速度優先で品質劣化なし |
| 構造解析・見出し抽出 | `LOW` 〜 `MEDIUM` | Lite モデルでも十分なケースが多い |
| 学術論文の要約・DNA 抽出 | `HIGH` | 文脈推論精度が品質に直結 |
| 翻訳（学術・長文） | `HIGH` | JSON/XML タグ維持・文脈整合性 |

---

## 4. 無料枠と Rate Limit

### 計測単位

Gemini API は以下の3軸で制限される：

- **RPM**: Requests Per Minute
- **TPM**: Tokens Per Minute（入力側）
- **RPD**: Requests Per Day

### 公式情報

Google は公式ドキュメントで具体値を**一切公開していない**。`https://ai.google.dev/gemini-api/docs/rate-limits` には「AI Studio のダッシュボードで確認せよ」とのみ記載（2026-05-18 更新確認済み）。

> [!NOTE]
> **公式制限値の確認方法**: [Google AI Studio](https://aistudio.google.com/rate-limit) → プロジェクト → 「Rate Limit」タブ。プロジェクトごと・モデルごとの現在値が表示される。

### 参考値（2026-05 時点・要 AI Studio 確認）

| モデル | 無料枠 RPM | 無料枠 RPD | 無料枠 TPM |
|---|---|---|---|
| `gemini-3.5-flash` | 〜10 | 〜250 | 〜250,000 |
| `gemini-3-flash-preview` | 〜15 | 〜250〜500 | 〜250,000 |
| `gemini-3.1-flash-lite` | 〜30 | 〜1,000〜1,500 | 〜250,000〜1,000,000 |
| `gemini-3.1-pro-preview` | 〜5 | 〜100 | 〜250,000 |

> 2025-12 の無料枠改定で Flash 系の RPD が大幅削減された。Lite は相対的に余裕がある。

### 有料枠（Tier 1 以上）

- 概ね RPM=300〜2000、TPM=1M〜数 M
- 実質無制限に近いが、`gemini-3.1-pro-preview` のような高負荷モデルは別建てで上限あり

---

## 5. 価格（2026-05 時点・$/1M トークン）

| モデル | 入力 | 出力 |
|---|---|---|
| `gemini-3.1-pro-preview`（200K 以下） | $2.00 | $12.00 |
| `gemini-3.1-pro-preview`（200K 超） | $4.00 | $18.00 |
| `gemini-3.5-flash` | $0.50 | $3.00 |
| `gemini-3-flash-preview` | $0.50 | $3.00 |
| `gemini-3.1-flash-lite` | $0.25 | $1.50 |

> thinking トークンも output レートで課金される点に注意。`HIGH` 多用時はコスト見積もりに含めること。

---

## 6. 429 / 503 エラーの対処パターン

無料枠で運用する場合、`429 RESOURCE_EXHAUSTED` または `503 UNAVAILABLE` が発生する。対処の定石：

### TierManager パターン（自動ダウンシフト）

```
1. 通常時: 高品質モデル（Flash / Pro）で実行
2. 429/503 検出: 例外をキャッチし、軽量モデル（Lite）へ内部状態を切替
3. 即座にリトライ: ダウンシフト後のモデルで処理を継続
4. プロセス継続: パニック終了せず、処理を完走させる
```

### 各 repo での実装

- **p2workflowy**: `core/llm_client.py` の `TierManager` シングルトン
- **eiyaku**: `core/llm_client.py` の `TierManager`
- **OCR**: `processor/tier_manager.py` の `TierManager`（`PAID(20並列/2000RPM) ↔ FREE(3並列/15RPM)`）

### 並列度の選び方

- **直列（concurrent=1）は非推奨**: 実測で約 50% 遅い
- **デフォルト**: `concurrent=4`
- **無料枠**: RPM 上限から逆算して `concurrent=3`（OCR の `--free` モードはこの設計）
- **有料枠**: `concurrent=8〜20`。ただし `max TTFT` が 200s 超のスパイクは API サーバー側混雑由来で常に発生し得る

---

## 7. 運用 Tips

### モデル名の変更があったとき

各 repo の以下の設定ファイルを更新する：

| repo | 設定ファイル | 主要キー |
|---|---|---|
| p2workflowy | `core/coreprompts.json` | `DEFAULT_MODEL` / `DEFAULT_MODEL_FREE` / `DEFAULT_MODEL_VLM` |
| eiyaku | `core/prompts.json` | `DEFAULT_MODEL` / `DEFAULT_MODEL_FREE` |
| OCR | `models.py` | `OCRConfig.model_id` |

> [!NOTE]
> p2workflowy・eiyaku は `@lru_cache` でプロンプトをキャッシュしているため、変更後はプロセス再起動が必須。

### 公式情報の参照先

- [Models](https://ai.google.dev/gemini-api/docs/models)（モデル ID 一覧）
- [Changelog](https://ai.google.dev/gemini-api/docs/changelog)（リリース・廃止情報）
- [Pricing](https://ai.google.dev/pricing)（価格）
- [Rate Limits](https://ai.google.dev/gemini-api/docs/rate-limits)（→ AI Studio へ誘導）
- [Thinking](https://ai.google.dev/gemini-api/docs/thinking)（thinking_level 詳細）

### 更新フロー

1. 上記公式ページで最新情報を確認
2. `~/Code/shared/gemini_models.md` を編集
3. `~/Code/shared/sync.sh` を実行
4. 各 repo で `git add docs/gemini_models.md && git commit -m "sync gemini_models.md"`
