"""
実験3: 画像を物理的にピクセル結合して1枚の合成画像として送る方式(stitch)と、
複数画像をパーツとして1リクエストに束ねる方式(multipart, 既存のextract_batch)を
同条件(同じN・同じユニット)で比較する。

会話の最初に検討した「media_resolutionのトークン予算は画像ごとに固定されるため、
ピクセル結合すると1画像あたりの実効解像度が下がるのでは」という仮説を、
実際のprompt_tokens数と精度の両面で検証する。

対象: Sample/morita.pdf (find_gutter_x修正後、8ユニット: 4見開き x R/L)
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
from processor.prompts import BASE_RULES

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
MODEL_ID = "gemini-3.1-flash-lite"
THINKING_BUDGET = 512

PDF_PATH = Path(__file__).resolve().parent.parent / "Sample" / "morita.pdf"
OUT_DIR = Path(__file__).resolve().parent / "out"
IMG_DIR = OUT_DIR / "morita_units_fixed"
STITCH_DIR = OUT_DIR / "stitched"
REF_PATH = Path(__file__).resolve().parent.parent / "Sample" / "morita_ocr.txt"
STITCH_DIR.mkdir(exist_ok=True, parents=True)

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
                    units.append({"name": p.name, "path": p, "is_group_start": is_start})
        else:
            paths, label, two = detector.analyze_layout_and_split(img, stem, "F", IMG_DIR)
            for p in paths:
                lbl, is_start = parse_side_label(p)
                units.append({"name": p.name, "path": p, "is_group_start": is_start})
    return units


def chunk(lst, size):
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def stitch_images(units_group, out_path):
    """縦書き右→左の読み順に合わせて、先頭ユニットを右端に配置して横結合する"""
    imgs = [Image.open(u["path"]) for u in units_group]
    max_h = max(im.height for im in imgs)
    resized = []
    for im in imgs:
        if im.height != max_h:
            new_w = int(im.width * max_h / im.height)
            im = im.resize((new_w, max_h))
        resized.append(im)
    total_w = sum(im.width for im in resized)
    canvas = Image.new("RGB", (total_w, max_h), "white")
    # 先頭ユニット(最初に読む)を右端に配置 -> 逆順に左から貼っていく
    x = 0
    for im in reversed(resized):
        canvas.paste(im, (x, 0))
        x += im.width
    canvas.save(out_path, "JPEG", quality=90)
    return out_path


STITCH_PROMPT = """指示：日本語書籍（縦書き）の超高精度テキスト化・複数ページ結合画像

この1枚の画像には、{n}ページ分の内容が右から左の読み順で横に結合されています（一番右が最初のページ、一番左が最後のページ）。
各ページを右から順に処理し、各ページのテキスト化結果の直後に区切りマーカー "<<<PAGE_BREAK>>>" を単独行として出力してください（最後のページの後にも出力すること）。
ページをまたいで文章が論理的に続いている場合でも、区切りマーカーは必ずページの境界ごとに1つ出力し、テキスト自体は自然に連結してください（マーカーは出力の区切りのためだけのものです）。

{prev_context_block}
""" + BASE_RULES


async def call_stitched(units_group, prev_context):
    idx = "_".join(u["name"].replace(".jpg", "") for u in units_group)
    stitched_path = STITCH_DIR / f"stitch_{idx}.jpg"
    stitch_images(units_group, stitched_path)

    prev_block = ""
    if prev_context:
        prev_block = f"【前ページの文脈】\n以下は直前のページの末尾です。冒頭が論理的に続くようにしてください。\n---\n{prev_context}\n---\n"

    prompt = STITCH_PROMPT.format(n=len(units_group), prev_context_block=prev_block)
    with open(stitched_path, "rb") as f:
        image_data = f.read()

    t0 = time.time()
    resp = await client.aio.models.generate_content(
        model=MODEL_ID,
        contents=[prompt, types.Part.from_bytes(data=image_data, mime_type="image/jpeg")],
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
        "stitched_path": str(stitched_path),
        "stitched_size": Image.open(stitched_path).size,
    }


MULTIPART_PROMPT = """指示：日本語書籍（縦書き）の超高精度テキスト化・複数ページ一括処理

これから{n}枚の画像を順番に提示します。これらは同じ本の連続したページを、読む順序（右→左、ページ送り順）に並べたものです。
各画像を提示順に処理し、各画像のテキスト化結果の直後に区切りマーカー "<<<PAGE_BREAK>>>" を単独行として出力してください（最後の画像の後にも出力すること）。
ページをまたいで文章が論理的に続いている場合でも、区切りマーカーは必ず画像の境界ごとに1つ出力し、テキスト自体は自然に連結してください（マーカーは出力の区切りのためだけのものです）。

{prev_context_block}
""" + BASE_RULES


async def call_multipart(units_group, prev_context):
    prev_block = ""
    if prev_context:
        prev_block = f"【前ページの文脈】\n以下は直前のページの末尾です。冒頭が論理的に続くようにしてください。\n---\n{prev_context}\n---\n"
    prompt = MULTIPART_PROMPT.format(n=len(units_group), prev_context_block=prev_block)

    contents = [prompt]
    for u in units_group:
        with open(u["path"], "rb") as f:
            contents.append(types.Part.from_bytes(data=f.read(), mime_type="image/jpeg"))

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


async def run_mode(units, size, mode):
    groups = chunk(units, size)
    all_texts = []
    total_calls = 0
    total_dt = 0.0
    total_in = 0
    total_out = 0
    anomalies = []
    prev_text = ""
    for g in groups:
        if mode == "stitch":
            r = await call_stitched(g, prev_text[-300:] if prev_text else "")
        else:
            r = await call_multipart(g, prev_text[-300:] if prev_text else "")
        total_calls += 1
        total_dt += r["duration"]
        total_in += r["prompt_tokens"]
        total_out += r["candidate_tokens"]
        if r["detected"] != r["expected"]:
            anomalies.append((mode, size, [u["name"] for u in g], f"検出{r['detected']}/期待{r['expected']}"))
        for i, u in enumerate(g):
            text = r["parts"][i] if i < len(r["parts"]) else ""
            all_texts.append(text)
        prev_text = r["parts"][-1] if r["parts"] else ""
        if mode == "stitch":
            print(f"    [{mode} n={size}] {[u['name'] for u in g]} -> stitched_size={r['stitched_size']} in_tok={r['prompt_tokens']} out_tok={r['candidate_tokens']} {r['duration']:.1f}s")
        else:
            print(f"    [{mode} n={size}] {[u['name'] for u in g]} -> in_tok={r['prompt_tokens']} out_tok={r['candidate_tokens']} {r['duration']:.1f}s")

    return {
        "mode": mode, "size": size, "calls": total_calls, "total_duration": total_dt,
        "total_in_tokens": total_in, "total_out_tokens": total_out,
        "unit_texts": all_texts, "anomalies": anomalies,
    }


def to_groups(unit_texts):
    return [unit_texts[0] + "\n" + unit_texts[1], unit_texts[2] + "\n" + unit_texts[3],
            unit_texts[4] + "\n" + unit_texts[5], unit_texts[6] + "\n" + unit_texts[7]]


def sim(a, b):
    return SequenceMatcher(None, a, b).ratio()


async def main():
    units = prepare_units()
    print(f"ユニット数: {len(units)}")
    ref_raw = REF_PATH.read_text(encoding="utf-8")
    ref_groups = [g.strip() for g in re.split(r"--- Page Group \d+ ---", ref_raw) if g.strip()]

    results = {}
    for size in [2, 4]:
        for mode in ["multipart", "stitch"]:
            print(f"\n=== {mode} n={size} ===")
            res = await run_mode(units, size, mode)
            groups = to_groups(res["unit_texts"])
            sims = [sim(ref_groups[i], groups[i]) for i in range(4)]
            res["avg_similarity"] = sum(sims) / len(sims)
            res["group_similarities"] = sims
            key = f"{mode}_n{size}"
            results[key] = res
            print(f"  calls={res['calls']} time={res['total_duration']:.1f}s in={res['total_in_tokens']} out={res['total_out_tokens']} avg_sim={res['avg_similarity']:.3f}")
            if res["anomalies"]:
                print(f"  異常: {res['anomalies']}")

    print("\n\n=== 総合比較表 ===")
    print(f"{'mode/n':<16}{'calls':>6}{'time(s)':>9}{'in_tok':>8}{'out_tok':>8}{'avg_sim':>9}")
    for key, r in results.items():
        print(f"{key:<16}{r['calls']:>6}{r['total_duration']:>9.1f}{r['total_in_tokens']:>8}{r['total_out_tokens']:>8}{r['avg_similarity']:>9.3f}")

    save_data = {k: {kk: vv for kk, vv in v.items()} for k, v in results.items()}
    (OUT_DIR / "pixel_stitch_comparison.json").write_text(json.dumps(save_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保存: {OUT_DIR / 'pixel_stitch_comparison.json'}")


if __name__ == "__main__":
    asyncio.run(main())
