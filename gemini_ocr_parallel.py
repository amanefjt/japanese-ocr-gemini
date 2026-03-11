import os
import re
import time
import asyncio
import argparse
import tempfile
from pathlib import Path
from datetime import datetime
import numpy as np
from PIL import Image
from pdf2image import convert_from_path
from google import genai
from google.genai import types
from dotenv import load_dotenv
from aiolimiter import AsyncLimiter

load_dotenv()
API_KEY = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
MODEL_ID = "gemini-3.1-flash-lite-preview"
DPI = 300
START_PAGE = 1
END_PAGE = 5
TWO_COLUMN_THRESHOLD = 0.2

OCR_PROMPT_STRUCTURED = "あなたはデータ入力エキスパートです。画像内の日本語テキストを書き出してください。"
OCR_PROMPT_RELAXED = "あなたはデータ入力エキスパートです。画像内の日本語テキストを見たとおりに書き出してください。"

def find_gutter_x(img_array: np.ndarray) -> int:
    height, width = img_array.shape
    x_min = int(width * 0.40)
    x_max = int(width * 0.60)
    col_sums = np.sum(img_array[:, x_min:x_max], axis=0)
    return x_min + int(np.argmax(col_sums))

def split_vertical_or_full(page_img, page_stem, side_label, out_dir):
    img_gray = page_img.convert("L")
    img_array = np.array(img_gray)
    arr = np.invert(img_array)
    h, w = arr.shape
    y_min, y_max = int(h * 0.35), int(h * 0.65)
    w_min, w_max = int(w * 0.40), int(w * 0.60)
    center_row_sums = np.sum(arr[y_min:y_max, w_min:w_max], axis=1).astype(float)
    window = 30
    if len(center_row_sums) >= window:
        smoothed = np.convolve(center_row_sums, np.ones(window)/window, mode='valid')
        idx = int(np.argmin(smoothed))
        split_y = y_min + idx + window // 2
        min_v = smoothed.min()
    else:
        idx = int(np.argmin(center_row_sums))
        split_y = y_min + idx
        min_v = center_row_sums.min()
    top_avg = center_row_sums[:idx].mean() if idx > 0 else 0
    bot_avg = center_row_sums[idx:].mean() if idx < len(center_row_sums) else 0
    avg = center_row_sums.mean()
    is_2col = (min_v < avg * TWO_COLUMN_THRESHOLD and top_avg > avg * 0.3 and bot_avg > avg * 0.3)
    if is_2col:
        img_top = page_img.crop((0, 0, w, split_y))
        img_bot = page_img.crop((0, split_y, w, h))
        tp = out_dir / f"{page_stem}_{side_label}_Top.jpg"
        bp = out_dir / f"{page_stem}_{side_label}_Bottom.jpg"
        img_top.save(tp, "JPEG", quality=95)
        img_bot.save(bp, "JPEG", quality=95)
        return [tp, bp], "二段組"
    else:
        fp = out_dir / f"{page_stem}_{side_label}_Full.jpg"
        page_img.save(fp, "JPEG", quality=95)
        return [fp], "一段組"

def extract_images_to_list(pdf_path, temp_dir):
    try:
        img_paths = convert_from_path(str(pdf_path), dpi=DPI, first_page=START_PAGE, last_page=END_PAGE, output_folder=str(temp_dir), fmt="jpeg", paths_only=True)
        img_paths = sorted([Path(p) for p in img_paths])
        final_paths = []
        for i, p in enumerate(img_paths):
            with Image.open(p) as img:
                arr = np.array(img.convert("L"))
                split_x = find_gutter_x(arr)
                ir = img.crop((split_x, 0, img.width, img.height))
                il = img.crop((0, 0, split_x, img.height))
                rp, _ = split_vertical_or_full(ir, p.stem, "R", temp_dir)
                final_paths.extend(rp)
                lp, _ = split_vertical_or_full(il, p.stem, "L", temp_dir)
                final_paths.extend(lp)
            p.unlink()
        return final_paths
    except Exception as e:
        print(f"Error in extraction: {e}")
        return []

async def call_gemini_async_with_retry(client, image_path, prompt, page_num, side, limiter):
    print(f"  Starting Item {page_num}...")
    for attempt in range(5):
        try:
            with open(image_path, "rb") as f: data = f.read()
            async with limiter:
                start = time.time()
                stream = await client.aio.models.generate_content_stream(
                    model=MODEL_ID, contents=[prompt, types.Part.from_bytes(data=data, mime_type="image/jpeg")],
                    config=types.GenerateContentConfig(temperature=0.0, thinking_config=types.ThinkingConfig(thinking_level="LOW"))
                )
                first = None
                async for chunk in stream:
                    if first is None: first = time.time()
                end = time.time()
                print(f"  [OK] Item {page_num:02}: TTFT={first-start:.2f}s, Total={end-start:.1f}s")
                return "DONE"
        except Exception as e:
            msg = str(e)
            if any(c in msg for c in ["429", "RESOURCE_EXHAUSTED"]):
                m = re.search(r'(?:retry in |after )(\d+)', msg); w = int(m.group(1)) + 1 if m else (2**attempt)+10
                await asyncio.sleep(w)
            else: print(f"  [x] Error {page_num}: {e}"); return "ERR"
    return "FAIL"

async def main():
    path = Path("Sample/hirano.pdf").absolute()
    if not path.exists(): print(f"File not found: {path}"); return
    client = genai.Client(api_key=API_KEY)
    limiter = AsyncLimiter(15, 60)
    sem = asyncio.Semaphore(1) # まずは直列に近い1
    
    print("\n--- テスト開始 ---")
    with tempfile.TemporaryDirectory() as tmp:
        image_paths = extract_images_to_list(path, Path(tmp))
        print(f"Extraction done. {len(image_paths)} images.")
        tasks = []
        for i, p in enumerate(image_paths):
            async def t(idx, pth):
                async with sem: return await call_gemini_async_with_retry(client, pth, OCR_PROMPT_STRUCTURED, idx+1, "N/A", limiter)
            tasks.append(t(i, p))
        start_all = time.time()
        await asyncio.gather(*tasks)
        print(f"--- 総時間: {time.time()-start_all:.1f}s ---")

if __name__ == '__main__':
    asyncio.run(main())
