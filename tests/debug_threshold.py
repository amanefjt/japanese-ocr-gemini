import sys
import numpy as np
from PIL import Image
from pdf2image import convert_from_path
from pathlib import Path

def analyze_page(img, name):
    arr = np.array(img.convert("L"))
    h, w = arr.shape
    y_min = int(h * 0.35)
    y_max = int(h * 0.65)
    
    # オリジナル (白=255)
    row_sums = np.sum(arr[y_min:y_max, :], axis=1).astype(float)
    whitest = row_sums.max()
    average = row_sums.mean()
    darkest = row_sums.min()
    
    # 反転 (白=0, 黒=255)
    inv_arr = 255 - arr
    
    # 全幅での判定
    inv_row_sums = np.sum(inv_arr[y_min:y_max, :], axis=1).astype(float)
    inv_blackest = inv_row_sums.max() # 最も文字が多い行
    inv_whitest = inv_row_sums.min() # 最も文字が少ない行（段間）
    inv_avg = inv_row_sums.mean()
    
    # 中央20%の幅での判定 (傾き対策)
    w_min = int(w * 0.40)
    w_max = int(w * 0.60)
    center_row_sums = np.sum(inv_arr[y_min:y_max, w_min:w_max], axis=1).astype(float)
    
    # 移動平均 (ウィンドウサイズ30px) を計算して細かい文字間の隙間を埋める
    window = 30
    if len(center_row_sums) >= window:
        smoothed_center = np.convolve(center_row_sums, np.ones(window)/window, mode='valid')
        smoothed_c_whitest = smoothed_center.min()
        smoothed_c_avg = smoothed_center.mean()
    else:
        smoothed_c_whitest = center_row_sums.min()
        smoothed_c_avg = center_row_sums.mean()
        
    c_whitest = center_row_sums.min()
    c_avg = center_row_sums.mean()
    
    print(f"--- {name} ---")
    if inv_whitest > 0:
        print(f"Full width: min(blank)={inv_whitest}, avg={inv_avg}, ratio_avg/min={inv_avg/inv_whitest:.4f}")
    else:
        print(f"Full width: min(blank)=0 (Perfectly clean), avg={inv_avg}")
        
    # 段間(ギャップ)の位置を特定 ( smoothed の最小値 )
    if len(center_row_sums) >= window:
        split_idx = np.argmin(smoothed_center) + window // 2
    else:
        split_idx = np.argmin(center_row_sums)
        
    top_avg = center_row_sums[:split_idx].mean() if split_idx > 0 else 0
    bottom_avg = center_row_sums[split_idx:].mean() if split_idx < len(center_row_sums) else 0
        
    c_whitest = center_row_sums.min()
    c_avg = center_row_sums.mean()
    
    print(f"--- {name} ---")
    if smoothed_c_whitest > 0:
        print(f"Smoothed Center 20%: min(blank)={smoothed_c_whitest:.1f}, top_avg={top_avg:.1f}, bottom_avg={bottom_avg:.1f}")
    else:
        print(f"Smoothed Center 20%: min(blank)=0 (Perfectly clean), top_avg={top_avg:.1f}, bottom_avg={bottom_avg:.1f}")

if __name__ == "__main__":
    pdf_path = "Sample/hirano.pdf"
    imgs = convert_from_path(pdf_path, dpi=300, first_page=1, last_page=10)
    
    for i, img in enumerate(imgs):
        arr = np.array(img.convert("L"))
        h, w = arr.shape
        x_min = int(w * 0.40)
        x_max = int(w * 0.60)
        col_sums = np.sum(arr[:, x_min:x_max], axis=0)
        split_x = x_min + int(np.argmax(col_sums))
        
        img_r = img.crop((split_x, 0, w, h))
        img_l = img.crop((0, 0, split_x, h))
        
        if i == 0 or i == 4:
            img_r.save(f"Sample/debug_p{i+1}_r.jpg")
            img_l.save(f"Sample/debug_p{i+1}_l.jpg")
        
        analyze_page(img_r, f"Page {i+1} Right")
        analyze_page(img_l, f"Page {i+1} Left")
