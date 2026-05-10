# NDLハイブリッドOCR（CLI版）実装計画

> **STATUS: CANCELLED — 2026-05-10**
> 理由: gemini-3.1-flash-lite-preview が安価すぎて50%削減の絶対額が無意味（1000ページ≈¥10）。
> 現行Gemini画像OCRの精度で十分なため、複雑性増加に見合わないと判断。
> 精度問題が発生した場合に再検討する。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** NDL OCR Liteで文字認識（無料）→ Geminiにテキストのみ送信して段落整形、という2段階パイプラインをCLI版に追加し、Geminiトークン消費を約50%削減する。

**Architecture:** NDL OCR Lite をsubprocessで呼び出し、JSON出力をパースしてテキストブロック列を取得。それをGeminiにテキストのみ（画像なし）で送り段落再構成させる。NDL失敗・文字数不足の場合は既存のGemini画像OCRにフォールバックする。`prev_context`による逐次文脈引き継ぎは両ルートで維持。

**Tech Stack:** Python 3.9+, google-genai, aiolimiter, subprocess, pytest, NDL OCR Lite (外部ツール)

---

## ファイル構成

| 操作 | ファイル | 役割 |
|------|---------|------|
| 新規 | `processor/ndl_extractor.py` | NDL OCR Lite subprocess呼び出し → テキストブロック抽出 |
| 新規 | `processor/gemini_restructurer.py` | テキストのみ Gemini API呼び出し（段落整形） |
| 新規 | `tests/test_ndl_extractor.py` | NDLExtractor ユニットテスト |
| 新規 | `tests/test_gemini_restructurer.py` | GeminiTextRestructurer ユニットテスト |
| 変更 | `processor/prompts.py` | `RESTRUCTURE_PROMPT` を追加 |
| 変更 | `models.py` | `OCRConfig` に `use_ndl`, `ndl_path` を追加 |
| 変更 | `processor/ocr_orchestrator.py` | NDL→Geminiテキスト整形ルートを組み込み |
| 変更 | `gemini_ocr_v2.py` | `--no-ndl`, `--ndl-path` CLI引数を追加 |
| 変更 | `requirements.txt` | `pytest` を追加 |

---

## Task 1: NDL OCR Lite インストールとJSON出力形式の確認

**これはコードを書かない準備タスク。** 実際のJSON形式を確認してから Task 4 に進む。

**Files:**
- なし（環境セットアップのみ）

- [ ] **Step 1: NDL OCR Lite をクローン・インストール**

```bash
# 任意の場所にクローン（プロジェクトの外を推奨）
git clone https://github.com/ndl-lab/ndlocr-lite ~/ndlocr-lite
cd ~/ndlocr-lite
pip install -r requirements.txt
```

- [ ] **Step 2: テスト画像でOCRを実行してJSON出力を確認**

```bash
mkdir -p /tmp/ndl_test
python3 ~/ndlocr-lite/ocr.py \
  --sourceimg /Users/shufujita/Code/OCR/Sample/Ronbun/debug_p1_l.jpg \
  --output /tmp/ndl_test \
  --json-only
ls /tmp/ndl_test/
```

期待: JSONファイルが1つ生成される（ファイル名を確認）

- [ ] **Step 3: JSON構造を確認して Task 4 の実装方針を決める**

```bash
python3 -m json.tool /tmp/ndl_test/*.json | head -80
```

**確認すること:**
- トップレベルの型（list or dict）
- テキストが入っているキー名（`"text"`, `"Text"`, `"String"` など）
- 読み順が保証されているか（フィールド名や配列の順序）

**→ Task 4 の `_parse_blocks()` を実際の形式に合わせて調整する**

- [ ] **Step 4: 環境変数を設定**

```bash
# .env に追記
echo "NDLOCR_PATH=/Users/$(whoami)/ndlocr-lite" >> /Users/shufujita/Code/OCR/.env
```

---

## Task 2: `requirements.txt` に pytest を追加

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: pytest を追加**

`requirements.txt` の末尾に追加:

```
pytest
```

- [ ] **Step 2: インストール確認**

```bash
pip install pytest
pytest --version
```

期待出力例: `pytest 9.x.x`

- [ ] **Step 3: コミット**

```bash
git add requirements.txt
git commit -m "chore: add pytest to requirements"
```

---

## Task 3: `models.py` に NDL設定フィールドを追加

**Files:**
- Modify: `models.py:1-33`

- [ ] **Step 1: `OCRConfig` に2フィールドを追加**

`models.py` の `OCRConfig` クラスに追記:

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

@dataclass(frozen=True)
class OCRConfig:
    """OCR実行の設定を保持するクラス"""
    api_key: str
    model_id: str = "gemini-3.1-flash-lite-preview"
    dpi: int = 300
    start_page: int = 1
    end_page: Optional[int] = None
    is_free_tier: bool = False
    concurrency: int = 20
    rpm_limit: int = 2000
    two_column_threshold: float = 0.2
    use_ndl: bool = True                   # ← 追加
    ndl_path: Optional[Path] = None        # ← 追加

    @classmethod
    def from_args(cls, args, api_key: str):
        ndl_path = Path(args.ndl_path) if getattr(args, 'ndl_path', None) else None
        if args.free:
            return cls(
                api_key=api_key,
                is_free_tier=True,
                concurrency=3,
                rpm_limit=15,
                start_page=args.start,
                end_page=args.end,
                use_ndl=not getattr(args, 'no_ndl', False),
                ndl_path=ndl_path,
            )
        return cls(
            api_key=api_key,
            start_page=args.start,
            end_page=args.end,
            use_ndl=not getattr(args, 'no_ndl', False),
            ndl_path=ndl_path,
        )
```

- [ ] **Step 2: 動作確認**

```bash
cd /Users/shufujita/Code/OCR
python3 -c "
from models import OCRConfig
import argparse
args = argparse.Namespace(free=False, start=1, end=None, no_ndl=False, ndl_path='/tmp/ndl')
cfg = OCRConfig.from_args(args, 'test_key')
print(cfg.use_ndl, cfg.ndl_path)
"
```

期待出力: `True /tmp/ndl`

- [ ] **Step 3: コミット**

```bash
git add models.py
git commit -m "feat: add use_ndl and ndl_path fields to OCRConfig"
```

---

## Task 4: `processor/prompts.py` に `RESTRUCTURE_PROMPT` を追加

**Files:**
- Modify: `processor/prompts.py`

- [ ] **Step 1: テキスト整形用プロンプトを追加**

`processor/prompts.py` の末尾に追記:

```python
# テキストブロック→段落再構成用（画像なし・NDLハイブリッドモード）
RESTRUCTURE_PROMPT = CONTEXT_ADVISOR + """指示：日本語書籍テキストの段落再構成
以下の【テキストブロック】はOCRエンジンが物理的なブロック単位で抽出した生テキストです。
読み順には並んでいますが、行・段・ページの境界で不自然に分断されています。
これを本来の段落構造に戻してテキスト化してください。

""" + BASE_RULES
```

- [ ] **Step 2: インポート確認**

```bash
cd /Users/shufujita/Code/OCR
python3 -c "from processor.prompts import RESTRUCTURE_PROMPT; print(RESTRUCTURE_PROMPT[:80])"
```

期待: プロンプト先頭80文字が表示される（エラーなし）

- [ ] **Step 3: コミット**

```bash
git add processor/prompts.py
git commit -m "feat: add RESTRUCTURE_PROMPT for NDL hybrid text-only mode"
```

---

## Task 5: `processor/ndl_extractor.py` を作成（TDD）

**Files:**
- Create: `processor/ndl_extractor.py`
- Create: `tests/test_ndl_extractor.py`

- [ ] **Step 1: テストファイルを作成**

`tests/test_ndl_extractor.py`:

```python
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from processor.ndl_extractor import NDLExtractor


@pytest.fixture
def extractor():
    return NDLExtractor(Path("/fake/ndlocr"))


# _parse_blocks のユニットテスト

def test_parse_blocks_list_format(extractor):
    data = [{"text": "テキスト1"}, {"text": "テキスト2"}]
    result = extractor._parse_blocks(data)
    assert result == ["テキスト1", "テキスト2"]


def test_parse_blocks_contents_key(extractor):
    data = {"contents": [{"text": "AAA"}, {"text": "BBB"}]}
    result = extractor._parse_blocks(data)
    assert result == ["AAA", "BBB"]


def test_parse_blocks_unknown_format_returns_empty(extractor):
    data = {"unexpected": "structure"}
    result = extractor._parse_blocks(data)
    assert result == []


def test_extract_text_from_json_joins_with_newline(extractor):
    data = [{"text": "ブロック1"}, {"text": "ブロック2"}]
    result = extractor._extract_text_from_json(data)
    assert result == "ブロック1\nブロック2"


def test_extract_text_from_json_skips_empty_blocks(extractor):
    data = [{"text": "有効"}, {"text": ""}, {"text": "  "}, {"text": "次"}]
    result = extractor._extract_text_from_json(data)
    assert result == "有効\n次"


# extract() の統合テスト（subprocess をモック）

def test_extract_returns_none_on_subprocess_exception(extractor, tmp_path):
    with patch("subprocess.run", side_effect=Exception("failed")):
        result = extractor.extract(tmp_path / "img.jpg")
    assert result is None


def test_extract_returns_none_on_nonzero_returncode(extractor, tmp_path):
    with patch("subprocess.run", return_value=MagicMock(returncode=1)):
        result = extractor.extract(tmp_path / "img.jpg")
    assert result is None


def test_extract_returns_none_when_text_too_short(extractor, tmp_path):
    json_data = json.dumps([{"text": "短"}])

    def fake_run(*args, **kwargs):
        # JSON ファイルを output ディレクトリに書き込む
        out_dir = Path(kwargs.get("capture_output", None) and "/fake" or args[0][5])
        # subprocess.run の args[0] は list: ['python3', 'ocr.py', '--sourceimg', ..., '--output', <dir>, ...]
        cmd = args[0]
        out_idx = cmd.index("--output") + 1
        out_path = Path(cmd[out_idx]) / "result.json"
        out_path.write_text(json_data, encoding="utf-8")
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=fake_run):
        result = extractor.extract(tmp_path / "img.jpg")
    assert result is None  # 50文字未満


def test_extract_returns_text_when_sufficient(extractor, tmp_path):
    long_text = "あ" * 60
    json_data = json.dumps([{"text": long_text}])

    def fake_run(*args, **kwargs):
        cmd = args[0]
        out_idx = cmd.index("--output") + 1
        out_path = Path(cmd[out_idx]) / "result.json"
        out_path.write_text(json_data, encoding="utf-8")
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=fake_run):
        result = extractor.extract(tmp_path / "img.jpg")
    assert result == long_text
```

- [ ] **Step 2: テストを実行して FAIL を確認**

```bash
cd /Users/shufujita/Code/OCR
python3 -m pytest tests/test_ndl_extractor.py -v 2>&1 | head -30
```

期待: `ModuleNotFoundError: No module named 'processor.ndl_extractor'`

- [ ] **Step 3: `processor/ndl_extractor.py` を実装**

> **注意:** Task 1 で確認したJSON形式に合わせて `_parse_blocks` を調整すること。
> 以下はデフォルト実装（複数形式を試みるフォールバック付き）。

```python
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


class NDLExtractor:
    """NDL OCR Lite をsubprocess経由で呼び出し、テキストブロックを返す。"""

    MIN_TEXT_LENGTH = 50

    def __init__(self, ndl_script_path: Path):
        self.ndl_script = ndl_script_path / "ocr.py"

    def extract(self, image_path: Path) -> Optional[str]:
        """
        画像パスを受け取り、NDL OCRの結果を読み順テキストとして返す。
        失敗または文字数不足の場合は None を返す（Gemini画像OCRへのフォールバックサイン）。
        """
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                cmd = [
                    "python3", str(self.ndl_script),
                    "--sourceimg", str(image_path),
                    "--output", tmpdir,
                    "--json-only",
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode != 0:
                    return None

                json_files = sorted(Path(tmpdir).glob("*.json"))
                if not json_files:
                    return None

                with open(json_files[0], encoding="utf-8") as f:
                    data = json.load(f)

                text = self._extract_text_from_json(data)
                if len(text) < self.MIN_TEXT_LENGTH:
                    return None
                return text

        except Exception:
            return None

    def _extract_text_from_json(self, data) -> str:
        texts = [t for t in self._parse_blocks(data) if t.strip()]
        return "\n".join(texts)

    def _parse_blocks(self, data) -> list:
        """
        NDL OCR Lite JSON出力からテキストブロックのリストを返す。
        Task 1 で確認した実際の形式に合わせてここを調整すること。
        """
        # Format A: トップレベルが list
        if isinstance(data, list):
            return [str(b.get("text", "")) for b in data if isinstance(b, dict)]

        if isinstance(data, dict):
            # Format B: "contents" / "blocks" / "text_blocks" キー
            for key in ("contents", "blocks", "text_blocks", "TextRegion"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    # items が直接テキストを持つ場合
                    if items and isinstance(items[0], dict) and "text" in items[0]:
                        return [str(b.get("text", "")) for b in items]
                    # items がさらにネストしている場合（TextLine → String 等）
                    texts = []
                    for item in items:
                        if isinstance(item, dict):
                            for subkey in ("text", "Text", "String", "CONTENT"):
                                if subkey in item:
                                    texts.append(str(item[subkey]))
                                    break
                    if texts:
                        return texts

        return []
```

- [ ] **Step 4: テストを実行して PASS を確認**

```bash
python3 -m pytest tests/test_ndl_extractor.py -v
```

期待: 全テスト PASS（`test_extract_returns_none_when_text_too_short` と `test_extract_returns_text_when_sufficient` は `fake_run` の実装次第で調整が必要な場合あり）

- [ ] **Step 5: コミット**

```bash
git add processor/ndl_extractor.py tests/test_ndl_extractor.py
git commit -m "feat: add NDLExtractor with subprocess wrapper and fallback logic"
```

---

## Task 6: `processor/gemini_restructurer.py` を作成（TDD）

**Files:**
- Create: `processor/gemini_restructurer.py`
- Create: `tests/test_gemini_restructurer.py`

- [ ] **Step 1: `pytest.ini` を作成（asyncio モード設定）**

プロジェクトルートに `pytest.ini` を新規作成:

```ini
[pytest]
asyncio_mode = auto
```

これで `@pytest.mark.asyncio` デコレータ不要、全 `async def test_*` が自動で非同期テストとして扱われる。

- [ ] **Step 2: テストファイルを作成**

`tests/test_gemini_restructurer.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from models import OCRConfig, ProcessingUnit
from processor.gemini_restructurer import GeminiTextRestructurer
from processor.prompts import RESTRUCTURE_PROMPT


@pytest.fixture
def config():
    return OCRConfig(api_key="test_key", use_ndl=True, ndl_path=Path("/fake"))


@pytest.fixture
def unit():
    return ProcessingUnit(
        image_path=Path("/fake/img.jpg"),
        page_num=1,
        side_label="右ページ（一段組）",
        is_two_column=False,
        is_group_start=True,
        prompt="",
        prev_context="前ページの末尾テキスト",
    )


def make_async_stream(text: str):
    """テスト用の非同期ストリームを返す"""
    chunk = MagicMock()
    chunk.text = text
    chunk.usage_metadata = None

    async def gen():
        yield chunk

    return gen()


def test_restructure_prompt_contains_prev_context(unit):
    """RESTRUCTURE_PROMPT に prev_context が埋め込まれることを確認"""
    prompt = RESTRUCTURE_PROMPT.format(prev_context=unit.prev_context)
    assert unit.prev_context in prompt


def test_restructure_prompt_contains_base_rules():
    """RESTRUCTURE_PROMPT に BASE_RULES の文字列が含まれることを確認"""
    prompt = RESTRUCTURE_PROMPT.format(prev_context="")
    assert "Moat" in prompt  # BASE_RULES内の固有文字列


async def test_restructure_contents_is_text_only(config, unit):
    """Gemini API 呼び出しの contents がテキスト文字列のみ（画像なし）であることを確認"""
    restructurer = GeminiTextRestructurer(config)
    captured = {}

    # generate_content_stream はキーワード引数で呼ばれる (**kwargs で受ける)
    async def fake_stream(**kwargs):
        captured["contents"] = kwargs.get("contents", [])
        return make_async_stream("再構成されたテキスト")

    with patch.object(restructurer.client.aio.models, "generate_content_stream",
                      new=fake_stream):
        sem = asyncio.Semaphore(1)
        await restructurer.restructure("テキストブロック", unit, sem)

    assert len(captured["contents"]) == 1
    assert isinstance(captured["contents"][0], str)


async def test_restructure_returns_ok_on_success(config, unit):
    restructurer = GeminiTextRestructurer(config)

    # generate_content_stream は await されるので AsyncMock が必要
    with patch.object(
        restructurer.client.aio.models,
        "generate_content_stream",
        new=AsyncMock(return_value=make_async_stream("整形済みテキスト")),
    ):
        sem = asyncio.Semaphore(1)
        result = await restructurer.restructure("raw text", unit, sem)

    assert result.status == "OK"
    assert result.text == "整形済みテキスト"


async def test_restructure_returns_error_on_non_retryable_exception(config, unit):
    restructurer = GeminiTextRestructurer(config)

    with patch.object(
        restructurer.client.aio.models,
        "generate_content_stream",
        new=AsyncMock(side_effect=Exception("invalid argument")),
    ):
        sem = asyncio.Semaphore(1)
        result = await restructurer.restructure("raw text", unit, sem)

    assert result.status == "ERROR"
    assert "invalid argument" in result.error_message
```

- [ ] **Step 3: pytest-asyncio を追加してテストが FAIL することを確認**

```bash
pip install pytest-asyncio
python3 -m pytest tests/test_gemini_restructurer.py -v 2>&1 | head -20
```

期待: `ModuleNotFoundError: No module named 'processor.gemini_restructurer'`

`requirements.txt` に `pytest-asyncio` も追記しておく。

- [ ] **Step 4: `processor/gemini_restructurer.py` を実装**

```python
import asyncio
import re
import time
from pathlib import Path
from aiolimiter import AsyncLimiter
from google import genai
from google.genai import types
from models import OCRConfig, ProcessingUnit, OCRResult
from .tier_manager import tier_manager
from .prompts import RESTRUCTURE_PROMPT


class GeminiTextRestructurer:
    """NDL OCRのテキスト出力を Gemini（テキストのみ）で段落整形するクラス。"""

    def __init__(self, config: OCRConfig):
        self.config = config
        self.client = genai.Client(api_key=config.api_key)
        self.limiter = AsyncLimiter(config.rpm_limit, 60)

    def _refresh_limiter(self):
        current_rpm = tier_manager.settings.rpm_limit
        if self.limiter.max_rate != current_rpm:
            self.limiter = AsyncLimiter(current_rpm, 60)

    async def restructure(
        self,
        raw_text: str,
        unit: ProcessingUnit,
        sem: asyncio.Semaphore,
    ) -> OCRResult:
        """
        NDL OCRの生テキストを受け取り、Gemini（画像なし）で段落構造を整形する。
        TierManager・AsyncLimiter は GeminiExtractor と共有。
        """
        result = OCRResult(unit=unit)
        formatted_prompt = (
            RESTRUCTURE_PROMPT.format(prev_context=unit.prev_context)
            + "\n\n【テキストブロック】\n"
            + raw_text
        )
        generate_config = types.GenerateContentConfig(
            temperature=0.0,
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
        )

        for attempt in range(5):
            try:
                async with sem:
                    async with self.limiter:
                        start_time = time.time()
                        first_token_time = None
                        full_text = []

                        stream = await self.client.aio.models.generate_content_stream(
                            model=self.config.model_id,
                            contents=[formatted_prompt],  # テキストのみ、画像なし
                            config=generate_config,
                        )

                        async for chunk in stream:
                            if first_token_time is None:
                                first_token_time = time.time()
                            if chunk.text:
                                full_text.append(chunk.text)

                        end_time = time.time()
                        result.ttft = (first_token_time - start_time) if first_token_time else 0.0
                        result.duration = end_time - start_time

                        if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                            m = chunk.usage_metadata
                            result.prompt_tokens = m.prompt_token_count
                            result.candidate_tokens = m.candidates_token_count

                        result.text = "".join(full_text)
                        if result.text:
                            result.status = "OK"
                            return result

                        result.status = "ERROR"
                        result.error_message = "Empty response"
                        return result

            except Exception as e:
                err_msg = str(e)
                if any(code in err_msg for code in ["429", "RESOURCE_EXHAUSTED"]):
                    tier_manager.notify_429()
                    self._refresh_limiter()
                    match = re.search(r"(?:retry in |after )(\d+)", err_msg)
                    wait_sec = int(match.group(1)) + 1 if match else (2 ** attempt) + 10
                    await asyncio.sleep(wait_sec)
                elif any(code in err_msg for code in ["500", "503", "504"]):
                    await asyncio.sleep(5)
                else:
                    result.status = "ERROR"
                    result.error_message = err_msg
                    return result

        result.status = "RETRY_FAILED"
        result.error_message = "All retries failed"
        return result
```

- [ ] **Step 5: テストを実行して PASS を確認**

```bash
python3 -m pytest tests/test_gemini_restructurer.py -v
```

期待: 全テスト PASS

- [ ] **Step 6: コミット**

```bash
git add processor/gemini_restructurer.py tests/test_gemini_restructurer.py \
        requirements.txt pytest.ini
git commit -m "feat: add GeminiTextRestructurer for text-only paragraph restructuring"
```

---

## Task 7: `processor/ocr_orchestrator.py` にNDLルーティングを組み込む

**Files:**
- Modify: `processor/ocr_orchestrator.py:1-30` (import + `__init__`)
- Modify: `processor/ocr_orchestrator.py:54-81` (逐次処理ループ)

- [ ] **Step 1: import と `__init__` を変更**

`ocr_orchestrator.py` の先頭importに追加:

```python
from processor.ndl_extractor import NDLExtractor
from processor.gemini_restructurer import GeminiTextRestructurer
```

`__init__` を以下に変更:

```python
def __init__(self, config: OCRConfig):
    self.config = config
    self.detector = ImageDetector(config.two_column_threshold)
    self.extractor = GeminiExtractor(config)

    self.ndl_extractor = None
    self.restructurer = None
    if config.use_ndl and config.ndl_path and config.ndl_path.exists():
        self.ndl_extractor = NDLExtractor(config.ndl_path)
        self.restructurer = GeminiTextRestructurer(config)
```

- [ ] **Step 2: 逐次処理ループのOCR呼び出し部分を変更**

`run()` メソッド内の `res = await self.extractor.extract_text(updated_unit, sem)` の1行を以下に置き換え:

```python
if self.ndl_extractor:
    ndl_text = await asyncio.to_thread(
        self.ndl_extractor.extract, updated_unit.image_path
    )
    if ndl_text:
        res = await self.restructurer.restructure(ndl_text, updated_unit, sem)
    else:
        res = await self.extractor.extract_text(updated_unit, sem)
else:
    res = await self.extractor.extract_text(updated_unit, sem)
```

変更後の `run()` メソッド内の該当箇所（全体像）:

```python
results = []
prev_text = ""
for i, unit in enumerate(units):
    settings = tier_manager.settings
    sem = asyncio.Semaphore(settings.concurrency)

    updated_unit = ProcessingUnit(
        image_path=unit.image_path,
        page_num=unit.page_num,
        side_label=unit.side_label,
        is_two_column=unit.is_two_column,
        is_group_start=unit.is_group_start,
        prompt=unit.prompt,
        prev_context=prev_text[-300:] if prev_text else ""
    )

    if self.ndl_extractor:
        ndl_text = await asyncio.to_thread(
            self.ndl_extractor.extract, updated_unit.image_path
        )
        if ndl_text:
            res = await self.restructurer.restructure(ndl_text, updated_unit, sem)
        else:
            res = await self.extractor.extract_text(updated_unit, sem)
    else:
        res = await self.extractor.extract_text(updated_unit, sem)

    results.append(res)

    if res.status == "OK":
        prev_text = res.text
    else:
        prev_text = ""

    if (i + 1) % 5 == 0 or (i + 1) == len(units):
        print(f"  [Progress] {i + 1}/{len(units)} 画像完了...")
```

- [ ] **Step 3: 動作確認（インポートレベル）**

```bash
cd /Users/shufujita/Code/OCR
python3 -c "from processor.ocr_orchestrator import OCROrchestrator; print('OK')"
```

期待: `OK`

- [ ] **Step 4: コミット**

```bash
git add processor/ocr_orchestrator.py
git commit -m "feat: integrate NDL+Gemini hybrid routing in OCROrchestrator"
```

---

## Task 8: `gemini_ocr_v2.py` に CLI引数を追加

**Files:**
- Modify: `gemini_ocr_v2.py:9-17` (parse_args)
- Modify: `gemini_ocr_v2.py:19-51` (main)

- [ ] **Step 1: `parse_args()` に2引数を追加**

```python
def parse_args():
    parser = argparse.ArgumentParser(description="Gemini APIを使用した高機能OCR (Modular Version)")
    parser.add_argument("input_pdf", nargs="?", help="入力PDFファイルのパス")
    parser.add_argument("--free", action="store_true", help="無料枠制限 (15 RPM) で実行する")
    parser.add_argument("--single", action="store_true", help="強制的に単一ページモードで実行する")
    parser.add_argument("--spread", action="store_true", help="強制的に見開きモードで実行する")
    parser.add_argument("--start", type=int, default=1, help="開始ページ (1開始)")
    parser.add_argument("--end", type=int, help="終了ページ (省略時は最後まで)")
    parser.add_argument("--no-ndl", action="store_true",
                        help="NDL OCRを無効化してGemini画像OCRのみで実行する")
    parser.add_argument("--ndl-path", type=str,
                        help="NDL OCR Liteのインストールパス（未指定時はNDLOCR_PATH環境変数を使用）")
    return parser.parse_args()
```

- [ ] **Step 2: `main()` に NDLOCR_PATH 環境変数フォールバックを追加**

`load_dotenv()` の直後、`config = OCRConfig.from_args(args, api_key)` の前に追記:

```python
# --ndl-path 未指定時は環境変数 NDLOCR_PATH を使用
if not args.ndl_path:
    args.ndl_path = os.getenv('NDLOCR_PATH')
```

- [ ] **Step 3: ヘルプ表示で確認**

```bash
cd /Users/shufujita/Code/OCR
python3 gemini_ocr_v2.py --help
```

期待: `--no-ndl` と `--ndl-path` がオプション一覧に表示される

- [ ] **Step 4: コミット**

```bash
git add gemini_ocr_v2.py
git commit -m "feat: add --no-ndl and --ndl-path CLI flags"
```

---

## Task 9: 動作確認（hirano.pdf でスモークテスト）

**Files:**
- なし（テストのみ）

- [ ] **Step 1: --no-ndl（既存動作）で実行して動作確認**

```bash
cd /Users/shufujita/Code/OCR
python3 gemini_ocr_v2.py Sample/Ronbun/hirano.pdf --no-ndl --start 1 --end 1
```

期待: エラーなく `hirano_ocr_v2.txt` が生成される

- [ ] **Step 2: NDLモードで実行**

```bash
python3 gemini_ocr_v2.py Sample/Ronbun/hirano.pdf --start 1 --end 1
```

期待: `[TierManager]` や `NDL` 関連のログが出て、`hirano_ocr_v2.txt` が生成される

- [ ] **Step 3: 出力品質を比較**

```bash
diff Sample/Ronbun/hirano_ocr.txt hirano_ocr_v2.txt | head -40
```

確認事項:
- 主要なテキスト（吉本・平野の対話）が正しく含まれているか
- 段落の切れ方が元のGeminiのみの出力と大きく変わっていないか
- フォールバックが起きた場合はログに `NDL fallback` が表示されるか

> NDLが正しく動いている場合、ログに「NDL OCR → Gemini text restructure」相当の流れが見える。フォールバックした場合は既存動作と同じ。

- [ ] **Step 4: 最終コミット**

```bash
git add -A
git commit -m "feat: complete NDL hybrid OCR pipeline (Phase 1)"
```

---

## 補足：フォールバックが多発する場合のデバッグ

NDLが常にNoneを返す場合：

```bash
# NDL単体テスト
python3 ~/ndlocr-lite/ocr.py \
  --sourceimg /Users/shufujita/Code/OCR/Sample/Ronbun/debug_p1_l.jpg \
  --output /tmp/ndl_debug \
  --json-only
python3 -m json.tool /tmp/ndl_debug/*.json | head -50
```

出力されたJSON形式と `ndl_extractor.py` の `_parse_blocks()` が一致しているか確認し、必要に応じて `_parse_blocks` を修正する。
