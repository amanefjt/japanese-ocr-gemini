import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List
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

class OCROrchestrator:
    """OCR処理全体を統括するクラス (Orchestrator)"""
    
    def __init__(self, config: OCRConfig):
        self.config = config
        self.detector = ImageDetector(config.two_column_threshold)
        self.extractor = GeminiExtractor(config)

    async def run(self, input_pdf: Path, output_txt: Path, 
                  force_single: bool = False, force_spread: bool = False):
        """OCR処理の全工程を順番に実行する"""
        
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            
            # 1. PDFから画像抽出と判定
            print(f"[{datetime.now().strftime('%H:%M:%S')}] PDF画像変換・レイアウト分析中...")
            units = self._prepare_processing_units(
                input_pdf, temp_dir, force_single, force_spread
            )
            
            if not units:
                print("処理対象の画像が見つかりませんでした。")
                return

            # 2. OCR抽出 (Gemini API / 順次文脈引き継ぎ)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] OCR処理開始: 計{len(units)}画像を文脈を維持して順次処理\n")
            sem = asyncio.Semaphore(self.config.concurrency)
            
            results = []
            prev_text = ""
            for i, unit in enumerate(units):
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

            # 3. 結果の再構成とファイル出力
            constructor = ResultConstructor(output_txt)
            groups = constructor.construct(results)
            
            print(f"\n[完了] {groups} ページグループの処理に成功しました。")
            print(f"[出力先] {output_txt}")

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
