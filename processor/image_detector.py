import numpy as np
from PIL import Image
from pathlib import Path
from typing import Tuple, List
import logging

class ImageDetector:
    """画像の物理的特性を判定するクラス (Detector)"""
    
    def __init__(self, two_column_threshold: float = 0.2):
        self.two_column_threshold = two_column_threshold

    @staticmethod
    def find_gutter_x(img_array: np.ndarray) -> Tuple[int, bool]:
        """
        見開き画像のノド（綴じ目）のX座標を検出する。
        """
        height, width = img_array.shape
        x_min = int(width * 0.40)
        x_max = int(width * 0.60)
        
        col_sums = np.sum(img_array[:, x_min:x_max], axis=0).astype(float)
        
        window = 20
        if len(col_sums) > window:
            smoothed = np.convolve(col_sums, np.ones(window)/window, mode='valid')
            relative_idx = np.argmax(smoothed)
            max_val = smoothed.max()
            split_x = x_min + int(relative_idx) + window // 2
        else:
            relative_idx = np.argmax(col_sums)
            max_val = col_sums.max()
            split_x = x_min + int(relative_idx)

        avg_val = col_sums.mean()
        ratio_reliable = (max_val > avg_val * 1.1) and (avg_val < 250 * height)

        # 実サンプル(morita.pdf, matsumura.pdf)で検証したところ、綺麗にスキャンされた
        # 見開きは中央帯(40-60%)が全体的に白く、ピーク列が平均より突出しない
        # (ratio_reliable=False)ことが多い一方、ピーク列自体はほぼ純白(255)で
        # 綴じ目/ページ間の余白として十分信頼できるケースが大半だった。
        # そのため、ピーク列がほぼ純白ならそれだけでも信頼できると判定する。
        pure_white = 255 * height
        near_pure_white = max_val >= 0.985 * pure_white
        is_reliable = ratio_reliable or near_pure_white

        return split_x, is_reliable

    def analyze_layout_and_split(
        self,
        page_img: Image.Image,
        page_stem: str,
        side_label: str,
        out_dir: Path,
    ) -> Tuple[List[Path], str, bool]:
        """
        1ページ画像を受け取り、二段組か一段組かを自動判定して分割する。
        """
        img_gray = page_img.convert("L")
        img_array = np.array(img_gray)
        arr = np.invert(img_array)
        h, w = arr.shape

        y_min = int(h * 0.35)
        y_max = int(h * 0.65)
        w_min = int(w * 0.40)
        w_max = int(w * 0.60)
        
        center_row_sums = np.sum(arr[y_min:y_max, w_min:w_max], axis=1).astype(float)

        window = 30
        if len(center_row_sums) >= window:
            smoothed_center = np.convolve(center_row_sums, np.ones(window)/window, mode='valid')
            split_idx_relative = int(np.argmin(smoothed_center))
            split_y = y_min + split_idx_relative + window // 2
            inv_min = smoothed_center.min()
        else:
            split_idx_relative = int(np.argmin(center_row_sums))
            split_y = y_min + split_idx_relative
            inv_min = center_row_sums.min()

        split_idx = split_idx_relative + (window // 2 if len(center_row_sums) >= window else 0)
        top_avg = center_row_sums[:split_idx].mean() if split_idx > 0 else 0
        bottom_avg = center_row_sums[split_idx:].mean() if split_idx < len(center_row_sums) else 0
        inv_avg = center_row_sums.mean()

        is_two_column = (
            inv_min < inv_avg * self.two_column_threshold and
            top_avg > inv_avg * 0.3 and
            bottom_avg > inv_avg * 0.3
        )

        paths = []
        if is_two_column:
            img_top = page_img.crop((0, 0, w, split_y))
            img_bottom = page_img.crop((0, split_y, w, h))
            
            top_path = out_dir / f"{page_stem}_{side_label}_Top.jpg"
            bot_path = out_dir / f"{page_stem}_{side_label}_Bottom.jpg"
            img_top.save(top_path, "JPEG", quality=95)
            img_bottom.save(bot_path, "JPEG", quality=95)
            paths = [top_path, bot_path]
            label = "二段組（上下分割）"
        else:
            full_path = out_dir / f"{page_stem}_{side_label}_Full.jpg"
            page_img.save(full_path, "JPEG", quality=95)
            paths = [full_path]
            label = "一段組（分割なし）"

        return paths, label, is_two_column
