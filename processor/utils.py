from pathlib import Path
from typing import Tuple

def parse_side_label(img_path: Path) -> Tuple[str, bool]:
    """
    ファイル名のサフィックスから表示用ラベルと「右ページTop/Full」フラグを返す。
    フラグが True のときにページグループヘッダを出力する。
    """
    name = img_path.name
    if "_R_Top" in name:
        return "右ページ上段（二段組）", True
    elif "_R_Bottom" in name:
        return "右ページ下段（二段組）", False
    elif "_R_Full" in name:
        return "右ページ（一段組）", True
    elif "_L_Top" in name:
        return "左ページ上段（二段組）", False
    elif "_L_Bottom" in name:
        return "左ページ下段（二段組）", False
    elif "_L_Full" in name:
        return "左ページ（一段組）", False
    elif "_F_Top" in name:
        return "上段（単一ページ二段組）", True
    elif "_F_Bottom" in name:
        return "下段（単一ページ二段組）", False
    elif "_F_Full" in name:
        return "（単一ページ一段組）", True
    else:
        return "不明", True
