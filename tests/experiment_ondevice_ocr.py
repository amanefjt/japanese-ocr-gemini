"""
オンデバイス Apple Foundation Models (apple-fm-sdk) による縦書きOCRの実験。

背景: p2workflowyの設計メモ
(docs/superpowers/specs/2026-07-15-vertical-text-ocr-shortcut-design.md)
で検討された「画像を直接オンデバイスLLMに渡し、OCR単体を挟まず段落復元済み
テキストを一発で得る」アプローチを、このリポジトリのサンプルPDFと
processor/ 配下の見開き分割・二段組判定・プロンプト資産を流用して検証する。

前提: macOS 26.0+ / Apple Intelligence 有効 / `pip install apple-fm-sdk`
      (gocr本体はクラウドのGemini APIのみを使うため、この依存はgocrの
       requirements.txtには追加しない。専用venvで検証する)

実行方法:
    source ~/.venvs/gocr/bin/activate
    python tests/experiment_ondevice_ocr.py Sample/matsumura.pdf --crop both
    python tests/experiment_ondevice_ocr.py Sample/ethnopdfselected.pdf --crop gutter
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from pdf2image import convert_from_path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from processor.image_detector import ImageDetector
from processor.prompts import OCR_PROMPT_STRUCTURED, OCR_PROMPT_RELAXED

import apple_fm_sdk as fm

CONTEXT_CHARS = 300  # gocr方式: 前ユニット出力の末尾N文字をプロンプトに注入
MAX_RESPONSE_TOKENS = 4000


class OnDeviceUnit:
    def __init__(self, image_path: Path, label: str, prompt: str):
        self.image_path = image_path
        self.label = label
        self.prompt = prompt


def build_units(pdf_path: Path, work_dir: Path, crop_mode: str, detector: ImageDetector) -> list[OnDeviceUnit]:
    """gocrのOCROrchestrator._prepare_processing_units()と同じ見開き/二段組判定を
    流用しつつ、crop_mode で見開き分割方式を切り替える。
      - "gutter":   gocr本来のノド検出 (find_gutter_x)
      - "midpoint": ノド検出をせず常に幅の中点で強制分割 (LLM方式の比較対照)
    """
    img_paths = convert_from_path(str(pdf_path), dpi=300, output_folder=str(work_dir), fmt="jpeg", paths_only=True)
    img_paths = sorted(Path(p) for p in img_paths)

    units: list[OnDeviceUnit] = []
    for i, spread_path in enumerate(img_paths):
        with Image.open(spread_path) as img:
            img_array = np.array(img.convert("L"))
            height, width = img_array.shape
            is_spread_aspect = width / height > 1.1

            do_split = False
            split_x = width // 2
            if is_spread_aspect:
                if crop_mode == "midpoint":
                    do_split = True  # 信頼性チェックをせず常に中点で強制分割
                else:
                    split_x, is_reliable = detector.find_gutter_x(img_array)
                    do_split = is_reliable
                    if not is_reliable:
                        print(f"  見開き {i + 1:03}: [安全策] 綴じ目が不明瞭なため分割をスキップ")

            stem = spread_path.stem
            sides = []
            if do_split:
                sides = [("R", img.crop((split_x, 0, width, height))), ("L", img.crop((0, 0, split_x, height)))]
            else:
                sides = [("F", img)]

            for side_label, side_img in sides:
                paths, layout_label, is_two = detector.analyze_layout_and_split(side_img, stem, side_label, work_dir)
                print(f"  見開き {i + 1:03} [{side_label}]: {layout_label}")
                prompt = OCR_PROMPT_STRUCTURED if is_two else OCR_PROMPT_RELAXED
                for j, p in enumerate(paths):
                    sub_label = f"{side_label}-{'上' if j == 0 else '下'}" if is_two else side_label
                    units.append(OnDeviceUnit(p, f"{stem}_{sub_label}", prompt))
    return units


async def run_ocr(units: list[OnDeviceUnit]) -> list[dict]:
    model = fm.SystemLanguageModel()
    available, reason = model.is_available()
    if not available:
        raise RuntimeError(f"オンデバイスモデルが利用不可: {reason}")

    results = []
    prev_context = ""
    for i, unit in enumerate(units):
        session = fm.LanguageModelSession()  # gocr方式: 呼び出しごとに独立(ステートレス)
        image = fm.ImageAttachment(path=unit.image_path)
        formatted_prompt = unit.prompt.format(prev_context=prev_context)
        options = fm.GenerationOptions(temperature=0.0, maximum_response_tokens=MAX_RESPONSE_TOKENS)

        t0 = time.monotonic()
        try:
            text = await session.respond([formatted_prompt, image], options=options)
            status = "OK"
        except Exception as e:
            text = ""
            status = f"ERROR: {type(e).__name__}: {e}"
        elapsed = time.monotonic() - t0

        print(f"  [{i + 1}/{len(units)}] {unit.label}: {status} ({elapsed:.1f}s, {len(text)}文字)")
        results.append({"label": unit.label, "status": status, "text": text, "elapsed": elapsed})
        if status == "OK" and text:
            prev_context = text[-CONTEXT_CHARS:]

    return results


def main():
    parser = argparse.ArgumentParser(description="オンデバイスFoundation ModelsによるOCR実験")
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("--crop", choices=["gutter", "midpoint", "both"], default="both")
    parser.add_argument("--start", type=int, default=None)
    parser.add_argument("--end", type=int, default=None)
    args = parser.parse_args()

    out_dir = Path(__file__).parent / "out"
    out_dir.mkdir(exist_ok=True)
    detector = ImageDetector()

    modes = ["gutter", "midpoint"] if args.crop == "both" else [args.crop]
    for mode in modes:
        print(f"\n=== {args.pdf_path.name} / crop={mode} ===")
        work_dir = out_dir / f"{args.pdf_path.stem}_{mode}_work"
        work_dir.mkdir(exist_ok=True)

        units = build_units(args.pdf_path, work_dir, mode, detector)
        if args.start or args.end:
            start = (args.start or 1) - 1
            end = args.end or len(units)
            units = units[start:end]

        results = asyncio.run(run_ocr(units))

        out_txt = out_dir / f"{args.pdf_path.stem}_ondevice_{mode}.txt"
        with open(out_txt, "w", encoding="utf-8") as f:
            for r in results:
                f.write(f"\n----- {r['label']} [{r['status']}] ({r['elapsed']:.1f}s) -----\n")
                f.write(r["text"])
                f.write("\n")
        print(f"[出力] {out_txt}")


if __name__ == "__main__":
    main()
