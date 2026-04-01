from pathlib import Path
from typing import List
from models import OCRResult

class ResultConstructor:
    """結果の再構成とファイル出力を担当するクラス (Constructor)"""
    
    def __init__(self, output_path: Path):
        self.output_path = output_path

    def construct(self, results: List[OCRResult]):
        """OCR抽出結果をまとめ、ファイルに書き出す"""
        page_group_count = 0
        
        with open(self.output_path, "w", encoding="utf-8") as f:
            for result in results:
                if result.unit.is_group_start:
                    page_group_count += 1
                    f.write(f"\n\n--- Page Group {page_group_count} ---\n")
                
                if result.status == "OK":
                    f.write(result.text + "\n")
                else:
                    f.write(f"[[{result.status}: {result.unit.page_num} {result.unit.side_label}]]\n")
                    if result.error_message:
                        f.write(f"Reason: {result.error_message}\n")
                
                f.flush()
        
        return page_group_count
