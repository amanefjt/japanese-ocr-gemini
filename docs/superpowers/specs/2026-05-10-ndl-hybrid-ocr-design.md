# NDLハイブリッドOCR 設計仕様

**作成日：** 2026-05-10  
**ステータス：** Phase 1 実装準備中 / Phase 2 将来計画

---

## 背景と目的

現在のパイプラインはGemini APIに毎回画像を送信しており、**画像トークン**が支出の大部分を占める。NDL OCR Lite（国立国会図書館製、無料、ローカル実行）を文字認識に使い、Geminiへはテキストのみを送ることで、**品質を維持したまま約50%のトークン削減**を目指す。

対象用途：現代日本語の学術書・エッセイ（活版印刷）。古書・雑誌・手書きは対象外。

---

## プロジェクト全体計画

| Phase | 対象 | 内容 | ステータス |
|-------|------|------|------------|
| **Phase 1** | CLI版（Python） | NDL OCR Lite統合 | **← 今ここ** |
| **Phase 2** | Web版（index.html） | HuggingFace Inference API または ONNX Runtime Web による同等機能 | 将来 |

---

## Phase 1：CLI NDLハイブリッド統合

### パイプライン変更

```
【変更前】
PDF → pdf2image → 画像 → GeminiExtractor（画像+プロンプト） → テキスト

【変更後】
PDF → pdf2image → 画像 ┬→ NDLExtractor（無料） → テキストブロック
                       │                              ↓
                       │                   GeminiTextRestructurer（テキストのみ）
                       │                              ↓ 段落整形
                       └→ [フォールバック] GeminiExtractor（現行、画像あり）
```

### トークン削減の仕組み

| | 入力トークン | 出力トークン | 合計/ユニット |
|--|--|--|--|
| 現行（Gemini画像OCR） | 画像~1000 + プロンプト~300 | ~500 | ~1800 |
| 変更後（NDL + テキスト整形） | テキスト~400 + プロンプト~150 | ~400 | ~950 |

**→ 約50%削減（活字本で文字認識が正常な場合）**

### 新規コンポーネント

#### `processor/ndl_extractor.py`（新規）

NDL OCR Liteをsubprocessとして呼び出し、JSON出力をパースして読み順テキストを返す。

```python
class NDLExtractor:
    def __init__(self, ndl_script_path: Path):
        self.ndl_script_path = ndl_script_path

    def extract(self, image_path: Path) -> str | None:
        """
        NDL OCRを実行し、読み順に連結したテキストを返す。
        失敗または文字数不足（<50文字）の場合はNoneを返す。
        """
```

- 呼び出し: `python3 {ndl_script_path}/ocr.py --sourceimg {image} --output {tmpdir} --json-only`
- 出力JSONのテキストブロックを読み順に連結して返す
- 例外・空出力 → `None`（フォールバックのサイン）

#### `processor/gemini_restructurer.py`（新規）

NDLのテキスト出力を受け取り、**画像なし**でGeminiに段落整形を依頼する。

```python
class GeminiTextRestructurer:
    async def restructure(
        self, raw_text: str, prev_context: str, sem: asyncio.Semaphore
    ) -> OCRResult:
        """
        テキストブロックをGemini（テキストのみ）に送り段落構造を整形する。
        プロンプトはBASE_RULES + prev_contextを使用。
        TierManager・AsyncLimiterは既存のものを共有。
        """
```

#### `processor/ocr_orchestrator.py`（変更）

逐次ループ内に、NDL→Geminiテキスト整形ルートを追加する。

```python
# 変更後の処理ロジック（概念）
ndl_text = ndl_extractor.extract(unit.image_path)
if ndl_text:
    res = await restructurer.restructure(ndl_text, prev_context, sem)
else:
    res = await extractor.extract_text(unit, sem)  # 既存のフォールバック
```

#### `models.py`（変更）

`OCRConfig`に以下を追加：

```python
use_ndl: bool = True                  # NDLモードの有効/無効
ndl_path: Optional[Path] = None       # NDL OCR Liteのインストールパス
```

#### `gemini_ocr_v2.py`（変更）

CLIオプションを追加：
- `--no-ndl`：NDLを無効化し、現行のGemini画像OCRのみで動作

### NDL OCR Liteのインストール

NDL OCR Liteはpipパッケージではなく、独立したPythonアプリケーション。

```bash
# 推奨：プロジェクトのそと or 任意の場所にclone
git clone https://github.com/ndl-lab/ndlocr-lite /path/to/ndlocr-lite
cd /path/to/ndlocr-lite
pip install -r requirements.txt

# .env にパスを設定
NDLOCR_PATH=/path/to/ndlocr-lite
```

`OCRConfig.ndl_path`はenv変数`NDLOCR_PATH`から自動取得するか、CLIで`--ndl-path`として指定。

### フォールバック条件（品質ゲート）

以下のいずれかでGemini画像OCRにフォールバックする：

1. NDL subprocess がエラー終了
2. NDLの返却テキストが50文字未満
3. `--no-ndl` フラグが指定されている
4. `ndl_path` が設定されていない（NDL未インストール）

### prev_context の維持

`GeminiTextRestructurer`でも`GeminiExtractor`と同様に、直前ユニットの末尾300文字をプロンプトに渡す。フォールバックが混在しても文脈は正しく引き継がれる（オーケストレーター側で管理）。

---

## Phase 2：Web版 HuggingFace統合（将来計画）

### 目標

`index.html`（サーバーなし、ブラウザのみ）でもPhase 1と同等のトークン削減を実現する。

### 技術選択肢

| アプローチ | 概要 | 難易度 | 課題 |
|------------|------|--------|------|
| **HuggingFace Inference API** | NDLのONNXモデルをHFにホストし、ブラウザからAPIキーで呼び出す | 中 | NDLモデルのHFアップロード、HF APIキーの管理 |
| **ONNX Runtime Web** | NDLのONNXモデルをブラウザのWASM/WebGLで直接実行 | 高 | モデル重みのバンドル、JS前後処理の再実装 |
| **Tesseract.js** | 純JavaScript OCR（日本語縦書き対応） | 低 | NDLより精度が低い可能性 |

### Phase 2 着手前に確認すること

- [ ] Phase 1のNDL品質検証（hirano.pdfなどで実測）
- [ ] NDLのONNXモデルのライセンスが商用/再配布OKか確認
- [ ] HF Inference APIの無料枠レート制限の確認

---

## 変更しないもの

- `processor/image_detector.py`（見開き分割・二段組判定）
- `processor/result_constructor.py`（出力フォーマット）
- `processor/prompts.py`のBASE_RULES（Geminiへのテキスト整形指示に流用）
- TierManager（429ダウンシフト、GeminiTextRestructurerでも共有）
- Web版（index.html）の現行動作（Phase 2まで変更なし）
