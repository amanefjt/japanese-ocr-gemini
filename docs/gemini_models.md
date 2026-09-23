# Gemini API モデル情報（共通ドキュメント）

3アプリ（p2workflowy / eiyaku / OCR）で共有する Gemini API の最新モデル知見・運用ノウハウ。

- **正本の場所**: `~/Code/shared/gemini_models.md`
- **同期**: `~/Code/shared/sync.sh` を実行すると各 repo の `docs/gemini_models.md` に上書きコピーされる
- **最終更新**: 2026-09-10（§1 に `gemini-3.7-flash` / `gemini-3.8-flash` を GA として追加し `gemini-3.6-flash` を旧世代化、§2 推奨モデルを `gemini-3.8-flash` に更新、§4 に無料枠実測値（`p2out1` プロジェクト、2026-09-10）を追加、§5 `gemini-3.6-flash` の価格記載を訂正（旧 $1.50/$7.50 表記は誤り。実際は `gemini-3.7-flash` / `gemini-3.8-flash` と同額の期間限定価格）。出典: Google AI Studio ダッシュボード実測 + [公式 Pricing](https://ai.google.dev/gemini-api/docs/pricing) + [Gemini 3.8 Flash 公式ブログ](https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/)）
- 2026-07-22 更新分（§1 に `gemini-3.6-flash` / `gemini-3.5-flash-lite` を GA として追加、§3 thinking_level に `MINIMAL` 追加、§4 Rate Limit 実測更新）はそのまま下記に統合済み。

> [!IMPORTANT]
> このファイルは正本（`~/Code/shared/gemini_models.md`）から sync されたコピーです。**直接編集禁止**。修正は正本側で行い、`~/Code/shared/sync.sh` を実行してください。

---

## 1. 現行モデル一覧（2026-09-10 時点）

Google AI Studio で利用可能な主要 API モデル ID。GA = Generally Available（安定版）、Preview = 廃止リスクあり。

### テキスト・マルチモーダル（VLM 含む）

`gemini-3.6-flash`（2026-07-21）→ `gemini-3.7-flash`（2026-08-13）→ `gemini-3.8-flash`（2026-09-02）と約3週間おきに世代交代が続いている。いずれも「`gemini-3.6-flash` の後継」を名乗る連鎖で、**Lite 系列（`gemini-3.5-flash-lite`）に対応する 3.6/3.7/3.8 世代の後継は存在しない**（Flash-Lite 枠は現行 `gemini-3.5-flash-lite` のまま据え置き）。

| モデル ID | ステータス | 用途 | 備考 |
|---|---|---|---|
| `gemini-3.8-flash` | **GA**（2026-09-02 公開。出典: [公式ブログ](https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/)） | **`gemini-3.7-flash` の後継、現行最上位 Flash**。長期化するコーディング・自律エージェント・専門領域の多段階推論で優位（DeepSWE v1.1・HLE-Verified 等のベンチマークで 3.7 を上回る、Artificial Analysis Intelligence Index 59 vs 56） | デフォルト `thinking_level` = `medium`。**`HIGH` 時のトークン消費が `gemini-3.7-flash` 比で約 1.5〜1.7 倍という報告あり**（$/token は同額なので、タスクあたりの実コストは上がる点に注意） |
| `gemini-3.7-flash` | **GA**（2026-08-13 公開。出典: [公式ブログ](https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-3-7-flash/)） | **`gemini-3.6-flash` の後継**。`gemini-3.8-flash` 登場によりすでに旧世代化。効率重視タスク向けの位置づけ | デフォルト `thinking_level` = `medium`（推定、公式ページ未確認） |
| `gemini-3.6-flash` | GA（2026-07-21）。**`gemini-3.8-flash` の登場によりさらに旧世代化** | 前々世代 Flash。新規採用は `gemini-3.8-flash` を優先 | デフォルト `thinking_level` = `medium` |
| `gemini-3.5-flash-lite` | **GA**（公式ページ [latest-model](https://ai.google.dev/gemini-api/docs/latest-model?hl=ja) で確認、2026-07-22） | **`gemini-3.1-flash-lite` の後継**。3.5 ファミリーで最速・最低コスト、高スループット実行向け | デフォルト `thinking_level` = `minimal`。バッチ処理・VLM-OCR の第一候補 |
| `gemini-3.5-flash` | **GA**（2026-05-19 GA化。**`gemini-3.6-flash` の登場により旧世代化**） | 前世代 Flash。新規採用は `gemini-3.6-flash` を優先 | I/O 2026 で発表 |
| `gemini-3.1-pro-preview` | Preview | 現行フラグシップ Pro。複雑推論・エージェント | 2M トークン context |
| `gemini-3-flash-preview` | Preview | フロンティア性能を低コストで提供する Flash | 2026-01 から提供 |
| `gemini-3.1-flash-lite` | **GA**（2026-05-07 GA化。**`gemini-3.5-flash-lite` の登場により旧世代化**） | 前世代 Lite。新規採用は `gemini-3.5-flash-lite` を優先 | 旧 `-preview` は 2026-05-25 シャットダウン |
| `gemini-2.5-pro` | GA | 旧世代 Pro。レガシー互換用途 | 新規採用は非推奨 |
| `gemini-2.5-flash` | GA | 旧世代 Flash | 新規採用は非推奨 |
| `gemini-2.5-flash-lite` | GA | 旧世代 Lite | 新規採用は非推奨 |

### トークン上限（2026-07-10 確認）

`gemini-3.5-flash` / `gemini-3.1-flash-lite` はともに **入力 1,048,576 / 出力 65,536 トークン**（出典: [gemini-3.5-flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash) / [gemini-3.1-flash-lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite)）。長文パイプラインでも入力側が制約になることは実用上ほぼない。

`gemini-3.6-flash` / `gemini-3.7-flash` / `gemini-3.8-flash` / `gemini-3.5-flash-lite` はいずれも公式ページ（[latest-model](https://ai.google.dev/gemini-api/docs/latest-model?hl=ja)、2026-09-10 確認）によると **1,048,576 トークンのコンテキストウィンドウ、65,536 トークンの出力上限**で共通。thinking・computer use を含む組み込みツールをフルサポート。

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
| 高品質テキスト生成（翻訳・要約・構造解析） | `gemini-3.8-flash`（次点: `gemini-3.7-flash`） | `gemini-3.6-flash` の後継系列で現行最上位。**`gemini-3.6-flash` / `gemini-3.7-flash` / `gemini-3.8-flash` は価格・無料枠 Rate Limit が完全に同額・同枠**（§4・§5）なので、3.6 に留まる理由がない。3.7 は「効率重視」の位置づけだが価格が3.8と同額のため採用理由が薄い |
| 大量バッチ・低コスト処理（VLM OCR・前処理） | `gemini-3.5-flash-lite`（次点: `gemini-3.1-flash-lite`） | `gemini-3.1-flash-lite` の公式後継。Rate Limit は完全一致するが**価格は値上げ**（§5）。RPD・RPM は緩い。**3.6/3.7/3.8 世代に対応する Lite 後継は存在しない**ため Lite 系列はここが最新 |
| 複雑推論・エージェント | `gemini-3.1-pro-preview` | 2M context、Deep Think Mini 対応 |
| VLM（画像→テキスト） | `gemini-3.5-flash-lite` | OCR 用途で十分。Flash 系列はマルチモーダル対応 |

> [!NOTE]
> `gemini-3.8-flash` は `HIGH` 思考時に `gemini-3.7-flash` 比でトークン消費が約 1.5〜1.7 倍という報告がある（$/token は同額なので、タスクあたりの実コストは上がる）。学術論文の要約・DNA抽出・長文翻訳など `HIGH` を多用する用途では、切替後にコスト（TPM 消費ペース含む）を実測で確認すること。

### 移行戦略

- **新規プロジェクト**: `gemini-3.8-flash` / `gemini-3.5-flash-lite` を第一候補とする（`gemini-3.8-flash` は公式ブログで GA 確認済み、2026-09-02 公開）
- **既存プロジェクト（`gemini-3.6-flash` 利用中）**: `gemini-3.8-flash` へ切替。価格・無料枠 Rate Limit は同額・同枠のため切替コストは実質ゼロ（§4・§5）。ただし §2 冒頭の `HIGH` トークン消費増の注意点は要確認
- **既存プロジェクト（`gemini-3.5-flash` / `gemini-3.1-flash-lite` 利用中）**: 後継モデルは Rate Limit が完全一致しており切替の影響は小さいが、`gemini-3.5-flash-lite` は `gemini-3.1-flash-lite` より価格が上がっている（§5）ため、コスト試算をしてから切替えること
- **`-preview` 利用箇所**: changelog を月次で確認し、廃止日の 2 週間前までに GA 版へ切り替える
- **未検証の懸念**: `gemini-3.6-flash` と `gemini-3.5-flash` が無料枠 Rate Limit のバケットを共有していた前例（§4）があるため、`gemini-3.6/3.7/3.8-flash` も同様に無料枠 RPD を共有している可能性がある。共有している場合、世代交代しても無料枠の実効容量は増えない。次回 AI Studio ダッシュボードで3モデル同時に負荷をかけて確認すること

---

## 3. thinking_level の仕様

Gemini 3 系では `thinking_budget`（数値）から `thinking_level`（列挙値）へ変更された。

### 利用可能な値

| 値 | 想定レスポンス時間 | 用途 |
|---|---|---|
| `MINIMAL` | 最速（**`gemini-3.5-flash-lite` で新規確認**、2026-07-22） | 最安・最速。定型処理向け |
| `LOW` | 1〜3 秒 | 翻訳・分類・OCR など定型処理 |
| `MEDIUM` | 数秒〜十数秒 | 一般的な生成タスク（**2026 年から追加**） |
| `HIGH` | 30 秒以上もあり得る | Deep Think Mini モード。複雑推論・論文要約・構造解析 |

### 重要な仕様

- **デフォルト値はモデルごとに異なる**（2026-07-22 公式ページで確認・要修正点）: `gemini-3.6-flash` のデフォルトは `MEDIUM`、`gemini-3.5-flash-lite` のデフォルトは `MINIMAL`。旧世代（`gemini-3-*`, `gemini-3.1-*`, `gemini-3.5-flash`）はデフォルト `HIGH` とされていたため、モデル移行時はデフォルト挙動が変わる点に注意。いずれのモデルでも明示的に指定するのが安全。
- **課金**: thinking トークンは output トークンと同レートで課金される。
- **適用モデル**: Gemini 3 系列（`gemini-3-*`, `gemini-3.1-*`, `gemini-3.5-*`, `gemini-3.6-*`, `gemini-3.7-*`, `gemini-3.8-*`）。2.5 系列は旧 API（`thinking_budget`）のまま。`MINIMAL` は Flash-Lite 系列（`gemini-3.5-flash-lite` 等）のみで、Flash 本体系列（3.6/3.7/3.8）は `LOW`/`MEDIUM`/`HIGH` の3値。

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

### 実測値: 無料枠（2026-07-22, `jocr1` プロジェクト）

| モデル | RPM | RPD | TPM |
|---|---|---|---|
| `gemini-3.1-flash-lite` | 15 | 500 | 250,000 |
| `gemini-3.5-flash-lite` | 15 | 500 | 250,000 |
| `gemini-2.5-flash-lite` | 10 | 20 | 250,000 |
| `gemini-3.5-flash` | 5 | 20 | 250,000 |
| `gemini-3.6-flash` | 5 | 20 | 250,000 |
| `gemini-3-flash-preview` | 5 | 20 | 250,000 |
| `gemini-2.5-flash` | 5 | 20 | 250,000 |
| `gemini-3.1-pro-preview` | 0 | 0 | 0 |

> [!NOTE]
> `gemini-3.1-pro-preview` は無料枠では RPM/TPM/RPD すべて 0 = **事実上利用不可**（このプロジェクトでは無料枠での Pro へのアクセス権がない模様）。
>
> 過去バージョンの「参考値（2026-05 時点）」は非公式の推測値だったため、実測値に置き換えた。2025-12 の無料枠改定で Flash 系の RPD が大幅削減された経緯は変わらず有効。

### 実測値: 無料枠（2026-09-10, `p2out1` プロジェクト）

| モデル | RPM | RPD | TPM |
|---|---|---|---|
| `gemini-3.1-flash-lite` | 15 | 500 | 250,000 |
| `gemini-3.5-flash-lite` | 15 | 500 | 250,000 |
| `gemini-3.6-flash` | 5 | 20 | 250,000 |
| `gemini-3.7-flash` | 5 | 20 | 250,000 |
| `gemini-3.8-flash` | 5 | 20 | 250,000 |
| `gemini-2.5-flash` | 5 | 20 | 250,000 |
| `gemini-3.1-pro-preview` | 0 | 0 | 0 |

> [!IMPORTANT]
> `p2out1`（別プロジェクト）でも `jocr1` と同じ上限値が確認できた。`gemini-3.7-flash` / `gemini-3.8-flash` は `gemini-3.6-flash` と**全く同じ上限（RPM 5 / RPD 20 / TPM 250,000）**で、3.6→3.5-flash の先例（§4冒頭）と形が一致する。ただし上限値が同じというだけでは「同一バケットを共有しているか（3モデル合計で日20件なのか、各20件=最大60件使えるのか）」までは確認できていない。**未検証**（§2 移行戦略の「未検証の懸念」参照）。

### 実測値: 有料枠 Tier 2（2026-07-22, `Paidproject` プロジェクト）

| モデル | RPM | RPD | TPM |
|---|---|---|---|
| `gemini-2-flash-lite` | 20,000 | 無制限 | 10,000,000 |
| `gemini-3.1-flash-lite` | 10,000 | 350,000 | 10,000,000 |
| `gemini-3.5-flash-lite` | 10,000 | 350,000 | 10,000,000 |
| `gemini-2.5-flash-lite` | 10,000 | 無制限 | 10,000,000 |
| `gemini-2-flash` | 10,000 | 無制限 | 10,000,000 |
| `gemini-embedding-1` | 5,000 | 無制限 | 5,000,000 |
| `gemini-3.5-flash` | 2,000 | 100,000 | 3,000,000 |
| `gemini-3.6-flash` | 2,000 | 100,000 | 3,000,000 |
| `gemini-2.5-flash` | 2,000 | 100,000 | 3,000,000 |
| `gemini-3.1-pro-preview` | 1,000 | 50,000 | 5,000,000 |
| `gemini-2.5-pro` | 1,000 | 50,000 | 5,000,000 |

> [!IMPORTANT]
> `gemini-3.6-flash` は `gemini-3.5-flash` と、`gemini-3.5-flash-lite` は `gemini-3.1-flash-lite` と、**無料枠・有料枠(Tier 2) いずれも Rate Limit が完全一致**している。内部的に同じ枠（バケット）を共有しているとみられ、新旧モデル間の切替による Rate Limit 面の実質的な影響はないと考えてよい。
>
> Tier は Google 側の利用実績に応じて自動的に上がる制度（Tier 1 → Tier 2 → …）。上記は Tier 2 の実測値であり、Tier や課金状況によって異なる。

---

## 5. 価格（2026-09-10 更新・$/1M トークン）

| モデル | 入力 | 出力 | コンテキストキャッシュ |
|---|---|---|---|
| `gemini-3.1-pro-preview`（200K 以下） | $2.00 | $12.00 | — |
| `gemini-3.1-pro-preview`（200K 超） | $4.00 | $18.00 | — |
| `gemini-3.8-flash`（〜2026-12-31 の期間限定価格） | **$0.75** | **$3.75** | $0.075 |
| `gemini-3.7-flash`（〜2026-12-31 の期間限定価格） | **$0.75** | **$3.75** | $0.075 |
| `gemini-3.6-flash`（〜2026-12-31 の期間限定価格） | **$0.75** | **$3.75** | $0.075 |
| `gemini-3.8/3.7/3.6-flash`（2027-01-01 以降の標準価格） | $1.50 | $7.50 | $0.15 |
| `gemini-3.5-flash` | $1.50 | $9.00 | $0.15 |
| `gemini-3-flash-preview` | $0.50 | $3.00 | — |
| `gemini-3.5-flash-lite` | **$0.30** | **$2.50** | 未公開 |
| `gemini-3.1-flash-lite` | $0.25 | $1.50 | $0.025 |

出典: [公式 Pricing](https://ai.google.dev/gemini-api/docs/pricing)（2026-09-10 確認）、`gemini-3.8-flash` は加えて [公式ブログ](https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/)。キャッシュ保管は別途 $1.00/1M tok/時。

> [!WARNING]
> **本ドキュメントの過去バージョンにあった「`gemini-3.6-flash` = $1.50/$7.50（固定）」という記載は誤り**。2026-09-10 に公式 Pricing ページを再確認したところ、`gemini-3.6-flash` も `gemini-3.7-flash` / `gemini-3.8-flash` と同じ**期間限定価格（〜2026-12-31 は $0.75/$3.75、2027-01-01 から $1.50/$7.50 へ倍増）**の対象だった。過去の $1.50/$7.50 表記は 2027 年以降の標準価格を先取りして書いてしまったものとみられる。コスト試算は都度公式ページで確認すること。
>
> `gemini-3.5-flash` は **2026-05-19 の GA 化時に $0.50/$3.00 → $1.50/$9.00 へ 3 倍値上げ**された（Simon Willison の記事でも裏取り済み）。Preview 時代の価格を前提にしたコスト見積もりは要更新。
>
> **`gemini-3.6/3.7/3.8-flash` は現在すべて同額**（期間限定価格のため）。一方 **`gemini-3.5-flash-lite` は `gemini-3.1-flash-lite` より高い**（入力 $0.25 → $0.30 で +20%、出力 $1.50 → $2.50 で +67%）。§4 の Rate Limit が完全一致していたため当初「価格も同額を引き継ぐ可能性が高い」と推測したが、Lite 系列については誤りだった。新世代への切替時は Rate Limit だけでなく価格も個別に確認すること。

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
