"""
実験: 複数ページ画像を1回のGemini APIリクエストに複数Partとして束ねることで、
呼び出し回数を減らしつつ精度を落とさずに済むかを検証するスクリプト。

対象: Sample/morita.pdf（現行パイプラインで一段組・5ユニットに分割される）
比較:
  A) 現行方式: 1ユニット = 1 API呼び出し（逐次・前ページ文脈引き継ぎ）
  B) 提案方式: 全ユニットを1回の API 呼び出しに複数画像Partとして束ねる

出力: tests/out/baseline.json, tests/out/batched.json, 比較レポートを標準出力
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from difflib import SequenceMatcher

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image
from pdf2image import convert_from_path
from google import genai
from google.genai import types
from dotenv import load_dotenv
import os

from processor.image_detector import ImageDetector
from processor.utils import parse_side_label
from processor.prompts import OCR_PROMPT_STRUCTURED, OCR_PROMPT_RELAXED, BASE_RULES

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
MODEL_ID = "gemini-3.1-flash-lite"

PDF_PATH = Path(__file__).resolve().parent.parent / "Sample" / "morita.pdf"
OUT_DIR = Path(__file__).resolve().parent / "out"
IMG_DIR = OUT_DIR / "units"
OUT_DIR.mkdir(exist_ok=True)
IMG_DIR.mkdir(exist_ok=True)

client = genai.Client(api_key=API_KEY)


def prepare_units():
    detector = ImageDetector()
    imgs = convert_from_path(str(PDF_PATH), dpi=300)
    units = []  # list of dict: name, path, is_two_column, is_group_start
    for i, img in enumerate(imgs):
        img_array = np.array(img.convert("L"))
        h, w = img_array.shape
        is_spread = (w / h > 1.1)
        split_x, is_reliable = detector.find_gutter_x(img_array)
        do_split = is_spread and is_reliable
        stem = f"spread{i+1}"
        if do_split:
            img_r = img.crop((split_x, 0, w, h))
            img_l = img.crop((0, 0, split_x, h))
            for side, im in [("R", img_r), ("L", img_l)]:
                paths, label, two = detector.analyze_layout_and_split(im, stem, side, IMG_DIR)
                for p in paths:
                    lbl, is_start = parse_side_label(p)
                    units.append({"name": p.name, "path": p, "is_two_column": bool(two), "is_group_start": is_start})
        else:
            paths, label, two = detector.analyze_layout_and_split(img, stem, "F", IMG_DIR)
            for p in paths:
                lbl, is_start = parse_side_label(p)
                units.append({"name": p.name, "path": p, "is_two_column": bool(two), "is_group_start": is_start})
    return units


async def run_baseline(units):
    """現行方式: 1ユニット = 1コール、逐次・前ページ文脈引き継ぎ"""
    results = []
    prev_text = ""
    total_calls = 0
    t0 = time.time()
    for u in units:
        prompt_template = OCR_PROMPT_STRUCTURED if u["is_two_column"] else OCR_PROMPT_RELAXED
        formatted_prompt = prompt_template.format(prev_context=prev_text[-300:] if prev_text else "")
        with open(u["path"], "rb") as f:
            image_data = f.read()

        call_t0 = time.time()
        resp = await client.aio.models.generate_content(
            model=MODEL_ID,
            contents=[formatted_prompt, types.Part.from_bytes(data=image_data, mime_type="image/jpeg")],
            config=types.GenerateContentConfig(temperature=0.0),
        )
        call_dt = time.time() - call_t0
        total_calls += 1
        text = resp.text or ""
        prev_text = text
        usage = resp.usage_metadata
        results.append({
            "name": u["name"],
            "text": text,
            "duration": call_dt,
            "prompt_tokens": usage.prompt_token_count if usage else None,
            "candidate_tokens": usage.candidates_token_count if usage else None,
        })
        print(f"  [baseline] {u['name']}: {call_dt:.1f}s, {len(text)}文字")
    total_dt = time.time() - t0
    return {"mode": "baseline", "calls": total_calls, "total_duration": total_dt, "results": results}


BATCH_PROMPT_HEADER = """指示：日本語書籍（縦書き）の超高精度テキスト化・複数ページ一括処理

これから{n}枚の画像を順番に提示します。これらは同じ本の連続したページを、読む順序（右→左、ページ送り順）に並べたものです。
各画像を提示順に処理し、各画像のテキスト化結果の直後に区切りマーカー "<<<PAGE_BREAK>>>" を単独行として出力してください（最後の画像の後にも出力すること）。
ページをまたいで文章が論理的に続いている場合でも、区切りマーカーは必ず画像の境界ごとに1つ出力し、テキスト自体は自然に連結してください（マーカーは出力の区切りのためだけのものです）。

""" + BASE_RULES + """

【出力形式の例（画像が3枚の場合）】
（1枚目の本文）
<<<PAGE_BREAK>>>
（2枚目の本文）
<<<PAGE_BREAK>>>
（3枚目の本文）
<<<PAGE_BREAK>>>
"""


async def run_batched(units):
    """提案方式: 全ユニットを1回のAPI呼び出しに複数画像Partとして束ねる"""
    contents = [BATCH_PROMPT_HEADER.format(n=len(units))]
    for u in units:
        with open(u["path"], "rb") as f:
            image_data = f.read()
        contents.append(types.Part.from_bytes(data=image_data, mime_type="image/jpeg"))

    t0 = time.time()
    resp = await client.aio.models.generate_content(
        model=MODEL_ID,
        contents=contents,
        config=types.GenerateContentConfig(temperature=0.0),
    )
    dt = time.time() - t0
    usage = resp.usage_metadata
    full_text = resp.text or ""
    parts = [p.strip() for p in re.split(r"<<<PAGE_BREAK>>>", full_text)]
    parts = [p for p in parts if p != ""]

    print(f"  [batched] 1コール: {dt:.1f}s, 総{len(full_text)}文字, 検出ページ数={len(parts)} (期待={len(units)})")

    results = []
    for i, u in enumerate(units):
        text = parts[i] if i < len(parts) else ""
        results.append({"name": u["name"], "text": text})

    return {
        "mode": "batched",
        "calls": 1,
        "total_duration": dt,
        "prompt_tokens": usage.prompt_token_count if usage else None,
        "candidate_tokens": usage.candidates_token_count if usage else None,
        "detected_pages": len(parts),
        "expected_pages": len(units),
        "raw_text": full_text,
        "results": results,
    }


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


async def main():
    print("=== 1. ユニット準備 (PDF -> 画像 -> レイアウト判定) ===")
    units = prepare_units()
    for u in units:
        print(f"  {u['name']} two_column={u['is_two_column']} group_start={u['is_group_start']}")

    print(f"\n=== 2. Baseline (現行方式: {len(units)}コール逐次) ===")
    baseline = await run_baseline(units)
    (OUT_DIR / "baseline.json").write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== 3. Batched (提案方式: 1コールに{len(units)}画像を束ねる) ===")
    batched = await run_batched(units)
    (OUT_DIR / "batched.json").write_text(json.dumps(batched, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 4. 比較レポート ===")
    print(f"呼び出し回数: baseline={baseline['calls']}回 / batched={batched['calls']}回")
    print(f"合計所要時間: baseline={baseline['total_duration']:.1f}s / batched={batched['total_duration']:.1f}s")
    base_in = sum(r["prompt_tokens"] or 0 for r in baseline["results"])
    base_out = sum(r["candidate_tokens"] or 0 for r in baseline["results"])
    print(f"合計トークン: baseline in={base_in} out={base_out} / batched in={batched.get('prompt_tokens')} out={batched.get('candidate_tokens')}")
    print(f"ページ境界検出: {batched['detected_pages']} / 期待{batched['expected_pages']}")

    print("\n--- ページ別 類似度 (baselineをリファレンスとした文字列一致度) ---")
    for i, u in enumerate(units):
        base_text = baseline["results"][i]["text"]
        batch_text = batched["results"][i]["text"] if i < len(batched["results"]) else ""
        sim = similarity(base_text, batch_text)
        print(f"  {u['name']}: baseline={len(base_text)}文字, batched={len(batch_text)}文字, 類似度={sim:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
