"""
実験2: 束ねる画像枚数(1/2/3/5)を変えて、呼び出し回数・所要時間・精度・異常出力の
有無を比較する。修正済みの thinking_budget=512 設定(processor/gemini_extractor.py と同じ)を
全パターンで統一して使う。

対象: Sample/morita.pdf (5ユニット: spread1,spread2,spread3,spread4R,spread4L)
比較対象: Sample/morita_ocr.txt (安定版)
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
THINKING_BUDGET = 512  # gemini_extractor.py と同じ修正後の値

PDF_PATH = Path(__file__).resolve().parent.parent / "Sample" / "morita.pdf"
OUT_DIR = Path(__file__).resolve().parent / "out"
IMG_DIR = OUT_DIR / "units"
REF_PATH = Path(__file__).resolve().parent.parent / "Sample" / "morita_ocr.txt"
OUT_DIR.mkdir(exist_ok=True)
IMG_DIR.mkdir(exist_ok=True)

client = genai.Client(api_key=API_KEY)


def prepare_units():
    detector = ImageDetector()
    imgs = convert_from_path(str(PDF_PATH), dpi=300)
    units = []
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


def chunk(lst, size):
    return [lst[i:i + size] for i in range(0, len(lst), size)]


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


async def call_single(unit, prev_text):
    prompt_template = OCR_PROMPT_STRUCTURED if unit["is_two_column"] else OCR_PROMPT_RELAXED
    formatted_prompt = prompt_template.format(prev_context=prev_text[-300:] if prev_text else "")
    with open(unit["path"], "rb") as f:
        image_data = f.read()
    t0 = time.time()
    resp = await client.aio.models.generate_content(
        model=MODEL_ID,
        contents=[formatted_prompt, types.Part.from_bytes(data=image_data, mime_type="image/jpeg")],
        config=types.GenerateContentConfig(temperature=0.0, thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET)),
    )
    dt = time.time() - t0
    usage = resp.usage_metadata
    return {
        "text": resp.text or "",
        "duration": dt,
        "prompt_tokens": usage.prompt_token_count if usage else 0,
        "candidate_tokens": usage.candidates_token_count if usage else 0,
    }


async def call_batch(units_group):
    contents = [BATCH_PROMPT_HEADER.format(n=len(units_group))]
    for u in units_group:
        with open(u["path"], "rb") as f:
            image_data = f.read()
        contents.append(types.Part.from_bytes(data=image_data, mime_type="image/jpeg"))
    t0 = time.time()
    resp = await client.aio.models.generate_content(
        model=MODEL_ID,
        contents=contents,
        config=types.GenerateContentConfig(temperature=0.0, thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET)),
    )
    dt = time.time() - t0
    usage = resp.usage_metadata
    full_text = resp.text or ""
    parts = [p.strip() for p in re.split(r"<<<PAGE_BREAK>>>", full_text) if p.strip() != ""]
    return {
        "duration": dt,
        "prompt_tokens": usage.prompt_token_count if usage else 0,
        "candidate_tokens": usage.candidates_token_count if usage else 0,
        "detected": len(parts),
        "expected": len(units_group),
        "parts": parts,
    }


async def run_batch_size(units, size):
    """size=1 なら現行方式(逐次・前ページ文脈引き継ぎ)、size>=2 なら束ね方式"""
    results_per_unit = []  # 各ユニットごとのtext
    total_calls = 0
    total_dt = 0.0
    total_in = 0
    total_out = 0
    anomalies = []  # (unit_name, reason)

    if size == 1:
        prev_text = ""
        for u in units:
            r = await call_single(u, prev_text)
            total_calls += 1
            total_dt += r["duration"]
            total_in += r["prompt_tokens"]
            total_out += r["candidate_tokens"]
            prev_text = r["text"]
            results_per_unit.append(r["text"])
            if len(r["text"]) > 5000:
                anomalies.append((u["name"], f"異常に長い出力 {len(r['text'])}文字"))
    else:
        groups = chunk(units, size)
        for g in groups:
            r = await call_batch(g)
            total_calls += 1
            total_dt += r["duration"]
            total_in += r["prompt_tokens"]
            total_out += r["candidate_tokens"]
            if r["detected"] != r["expected"]:
                anomalies.append((", ".join(u["name"] for u in g), f"ページ境界不一致 検出{r['detected']}/期待{r['expected']}"))
            for i, u in enumerate(g):
                text = r["parts"][i] if i < len(r["parts"]) else ""
                results_per_unit.append(text)
                if len(text) > 5000:
                    anomalies.append((u["name"], f"異常に長い出力 {len(text)}文字"))

    return {
        "size": size,
        "calls": total_calls,
        "total_duration": total_dt,
        "total_in_tokens": total_in,
        "total_out_tokens": total_out,
        "unit_texts": results_per_unit,
        "anomalies": anomalies,
    }


def to_groups(unit_texts):
    """5ユニット -> 4ページグループ(reference形式)に変換"""
    return [unit_texts[0], unit_texts[1], unit_texts[2], unit_texts[3] + "\n" + unit_texts[4]]


def sim(a, b):
    return SequenceMatcher(None, a, b).ratio()


def count_asterisk_markers(text):
    return text.count("＊\n＊\n＊") + text.count("＊ ＊ ＊")


async def main():
    units = prepare_units()
    print(f"ユニット数: {len(units)}")

    ref_raw = REF_PATH.read_text(encoding="utf-8")
    ref_groups = [g.strip() for g in re.split(r"--- Page Group \d+ ---", ref_raw) if g.strip()]
    ref_asterisk_total = sum(1 for g in ref_groups if "＊" in g)

    all_results = {}
    for size in [1, 2, 3, 5]:
        print(f"\n=== batch_size={size} 実行中 ===")
        res = await run_batch_size(units, size)
        all_results[size] = res
        groups = to_groups(res["unit_texts"])
        sims = [sim(ref_groups[i], groups[i]) for i in range(4)]
        res["group_similarities"] = sims
        res["avg_similarity"] = sum(sims) / len(sims)
        res["asterisk_count"] = sum(1 for g in groups if "＊" in g)
        print(f"  calls={res['calls']} time={res['total_duration']:.1f}s in={res['total_in_tokens']} out={res['total_out_tokens']}")
        print(f"  group類似度={[f'{s:.3f}' for s in sims]} 平均={res['avg_similarity']:.3f}")
        print(f"  ＊区切り記号を含むグループ数: {res['asterisk_count']} / 参照{ref_asterisk_total}")
        if res["anomalies"]:
            print(f"  異常検出: {res['anomalies']}")
        else:
            print("  異常検出: なし")

    print("\n\n=== 総合比較表 ===")
    print(f"{'batch':>6} | {'calls':>5} | {'time(s)':>8} | {'in_tok':>7} | {'out_tok':>7} | {'avg_sim':>7} | {'asterisk':>8} | anomalies")
    for size in [1, 2, 3, 5]:
        r = all_results[size]
        print(f"{size:>6} | {r['calls']:>5} | {r['total_duration']:>8.1f} | {r['total_in_tokens']:>7} | {r['total_out_tokens']:>7} | {r['avg_similarity']:>7.3f} | {r['asterisk_count']:>8} | {len(r['anomalies'])}")

    # 保存
    save_data = {}
    for size, r in all_results.items():
        save_data[str(size)] = {k: v for k, v in r.items() if k != "unit_texts"} | {"unit_texts": r["unit_texts"]}
    (OUT_DIR / "batch_size_comparison.json").write_text(json.dumps(save_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保存: {OUT_DIR / 'batch_size_comparison.json'}")


if __name__ == "__main__":
    asyncio.run(main())
