import asyncio
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import numpy as np
from PIL import Image
from pdf2image import convert_from_path
from aiolimiter import AsyncLimiter

from models import OCRConfig, ProcessingUnit, OCRResult
from processor.image_detector import ImageDetector
from processor.gemini_extractor import GeminiExtractor
from processor.result_constructor import ResultConstructor
from processor.prompts import OCR_PROMPT_STRUCTURED, OCR_PROMPT_RELAXED
from processor.utils import parse_side_label
from processor.tier_manager import tier_manager, GeminiTier
from processor.model_rotator import model_rotator

class OCROrchestrator:
    """OCR処理全体を統括するクラス (Orchestrator)"""
    
    def __init__(self, config: OCRConfig):
        self.config = config
        self.detector = ImageDetector(config.two_column_threshold)
        self.extractor = GeminiExtractor(config)

    async def run(self, input_pdf: Path, output_txt: Path, 
                  force_single: bool = False, force_spread: bool = False):
        """OCR処理の全工程を順番に実行する"""
        
        start_ts = time.time()
        # パイプライン開始時にモデルローテーション状態を先頭へ楽観的にリセット
        model_rotator.reset()

        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)

            # 1. PDFから画像抽出と判定
            print(f"[{datetime.now().strftime('%H:%M:%S')}] PDF画像変換・レイアウト分析中...")

            # 初期ティアの設定
            if self.config.is_free_tier:
                tier_manager.set_tier(GeminiTier.FREE)
            else:
                tier_manager.set_tier(GeminiTier.PAID)

            rpd_limit = tier_manager.settings.rpd_limit
            if rpd_limit:
                print(f"  [無料枠] 1日のリクエスト上限は約{rpd_limit}回（2026-07-21 AI Studio実測）。")

            units = self._prepare_processing_units(
                input_pdf, temp_dir, force_single, force_spread
            )

            if not units:
                print("処理対象の画像が見つかりませんでした。")
                return

            # 2. OCR抽出 (Gemini API)
            use_parallel_pool = self.config.parallel_pool and self.config.is_free_tier
            if self.config.parallel_pool and not self.config.is_free_tier:
                print("  [警告] --parallel-pool は --free 指定時のみ有効です。通常の順次処理で実行します。")

            if use_parallel_pool:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] OCR処理開始 [実験的:並列プール]: "
                      f"計{len(units)}画像を{len(model_rotator.pool)}モデルへラウンドロビン発行\n")
                print("  [警告] 実地検証で段落の重複・欠落や誤字を確認済みの機能です。精度優先の場合は使用しないでください。")
                results = await self._run_paired_parallel(units)
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] OCR処理開始: 計{len(units)}画像を文脈を維持して順次処理\n")
                results = await self._run_sequential(units)

            # 3. 結果の再構成とファイル出力
            constructor = ResultConstructor(output_txt)
            groups = constructor.construct(results)

            elapsed = time.time() - start_ts
            print(f"\n[完了] {groups} ページグループの処理に成功しました。")
            print(f"[出力先] {output_txt}")
            print(f"[所要時間] {elapsed:.1f}秒")

    async def _run_sequential(self, units: List[ProcessingUnit]) -> List[OCRResult]:
        """既定の処理経路: 1画像ずつ、直前ページの末尾テキストを文脈として厳密に引き継ぐ"""
        results = []
        prev_text = ""
        for i, unit in enumerate(units):
            # 最新のティア設定に基づきセマフォを動的に取得
            settings = tier_manager.settings
            sem = asyncio.Semaphore(settings.concurrency)

            # 1つ前のユニットの末尾テキストを文脈としてセット
            # (見開きの右ページ -> 左ページ、または前ページ -> 次ページ)
            # ただし、前ページが存在しない場合は空文字
            updated_unit = ProcessingUnit(
                image_path=unit.image_path,
                page_num=unit.page_num,
                side_label=unit.side_label,
                is_two_column=unit.is_two_column,
                is_group_start=unit.is_group_start,
                prompt=unit.prompt,
                prev_context=prev_text[-300:] if prev_text else ""
            )

            res = await self.extractor.extract_text(updated_unit, sem)
            results.append(res)

            # エラー時は空文字、成功時は抽出テキストを文脈にセット
            if res.status == "OK":
                prev_text = res.text
            else:
                prev_text = ""

            # 進捗（簡易）
            if (i + 1) % 5 == 0 or (i + 1) == len(units):
                print(f"  [Progress] {i + 1}/{len(units)} 画像完了...")

        return results

    async def _run_paired_parallel(self, units: List[ProcessingUnit]) -> List[OCRResult]:
        """[実験的] 無料枠Liteプールへページペア単位でラウンドロビン発行し並列実行する。

        各モデルに専用のレートリミッタ(1req/4s相当)を割り当てて同時発行することで、
        429を待たずにスループット自体を上げる(p2workflowyのバッチ単位ラウンドロビンと同じ着想)。
        既知のトレードオフ: ペアの2枚目のユニットは「直前ページ」ではなく「2ページ前」の
        文脈を使うことになる(ペア内の1枚目と2枚目を同時発行するため、1枚目の結果を
        2枚目の文脈に使えない)。奇数個の余りは最後に単独で処理し、通常どおり直前文脈を使う。
        """
        pool = model_rotator.pool
        pool_limiters = {m: AsyncLimiter(self.config.rpm_limit, 60) for m in pool}
        pair_size = len(pool)
        sem = asyncio.Semaphore(max(self.config.concurrency, pair_size))

        results: List[Optional[OCRResult]] = [None] * len(units)
        prev_text = ""
        i = 0
        while i < len(units):
            batch = units[i:i + pair_size]
            tasks = []
            for j, unit in enumerate(batch):
                model = pool[j % len(pool)]
                updated_unit = ProcessingUnit(
                    image_path=unit.image_path,
                    page_num=unit.page_num,
                    side_label=unit.side_label,
                    is_two_column=unit.is_two_column,
                    is_group_start=unit.is_group_start,
                    prompt=unit.prompt,
                    prev_context=prev_text[-300:] if prev_text else ""
                )
                tasks.append(self.extractor.extract_text(
                    updated_unit, sem,
                    model_override=model,
                    limiter_override=pool_limiters[model],
                    model_pinned=True
                ))

            batch_results = await asyncio.gather(*tasks)
            for k, res in enumerate(batch_results):
                results[i + k] = res

            # 次バッチの文脈は、このバッチ内で最後に成功したユニットのテキストを使う
            for res in reversed(batch_results):
                if res.status == "OK":
                    prev_text = res.text
                    break
            else:
                prev_text = ""

            i += len(batch)
            print(f"  [Progress] {min(i, len(units))}/{len(units)} 画像完了...")

        return results

    def _prepare_processing_units(
        self, pdf_path: Path, temp_dir: Path, 
        force_single: bool, force_spread: bool
    ) -> List[ProcessingUnit]:
        """PDFを読み込み、ProcessingUnit のリストを作成する"""
        
        img_paths = convert_from_path(
            str(pdf_path),
            dpi=self.config.dpi,
            first_page=self.config.start_page,
            last_page=self.config.end_page,
            output_folder=str(temp_dir),
            fmt="jpeg",
            paths_only=True,
        )
        img_paths = sorted([Path(p) for p in img_paths])

        units = []
        for i, spread_path in enumerate(img_paths):
            with Image.open(spread_path) as img:
                img_array = np.array(img.convert("L"))
                height, width = img_array.shape
                
                is_spread_aspect = (width / height > 1.1)
                do_split = False
                split_x = width // 2
                
                if not force_single and (is_spread_aspect or force_spread):
                    split_x, is_reliable = self.detector.find_gutter_x(img_array)
                    if is_reliable:
                        do_split = True
                    else:
                        print(f"  見開き {i+1:03}: [安全策] 綴じ目が不明瞭なため分割をスキップします。")
                
                stem = spread_path.stem
                if do_split:
                    img_right = img.crop((split_x, 0, width, height))
                    img_left = img.crop((0, 0, split_x, height))
                    
                    # 右ページ
                    r_paths, r_label, r_two = self.detector.analyze_layout_and_split(img_right, stem, "R", temp_dir)
                    for j, p in enumerate(r_paths):
                        label, is_start = parse_side_label(p)
                        units.append(ProcessingUnit(
                            image_path=p, page_num=i+1, side_label=label, 
                            is_two_column=r_two, is_group_start=is_start,
                            prompt=OCR_PROMPT_STRUCTURED if r_two else OCR_PROMPT_RELAXED
                        ))
                    
                    # 左ページ
                    l_paths, l_label, l_two = self.detector.analyze_layout_and_split(img_left, stem, "L", temp_dir)
                    for j, p in enumerate(l_paths):
                        label, is_start = parse_side_label(p)
                        units.append(ProcessingUnit(
                            image_path=p, page_num=i+1, side_label=label, 
                            is_two_column=l_two, is_group_start=is_start,
                            prompt=OCR_PROMPT_STRUCTURED if l_two else OCR_PROMPT_RELAXED
                        ))
                else:
                    # 単一ページ
                    f_paths, f_label, f_two = self.detector.analyze_layout_and_split(img, stem, "F", temp_dir)
                    for j, p in enumerate(f_paths):
                        label, is_start = parse_side_label(p)
                        units.append(ProcessingUnit(
                            image_path=p, page_num=i+1, side_label=label, 
                            is_two_column=f_two, is_group_start=is_start,
                            prompt=OCR_PROMPT_STRUCTURED if f_two else OCR_PROMPT_RELAXED
                        ))

            spread_path.unlink()  # 元の見開き画像を削除してディスク節約
        
        return units
