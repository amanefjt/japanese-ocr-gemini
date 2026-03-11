from pdf2image import convert_from_path
import numpy as np
import sys
from PIL import Image

pdf_path = "Sample/hirano.pdf"
imgs = convert_from_path(pdf_path, dpi=300, first_page=2, last_page=2)
img = imgs[0]
arr = np.array(img.convert("L"))
h, w = arr.shape
x_min = int(w * 0.40)
x_max = int(w * 0.60)
col_sums = np.sum(arr[:, x_min:x_max], axis=0)
split_x = x_min + int(np.argmax(col_sums))
img_right = img.crop((split_x, 0, w, h))

# segment Right Top / Bottom
inv_arr = 255 - np.array(img_right.convert("L"))
y_min = int(h * 0.35)
y_max = int(h * 0.65)
w_min = int(img_right.width * 0.40)
w_max = int(img_right.width * 0.60)
center_row_sums = np.sum(inv_arr[y_min:y_max, w_min:w_max], axis=1).astype(float)
window = 30
smoothed_center = np.convolve(center_row_sums, np.ones(window)/window, mode='valid')
split_idx_relative = int(np.argmin(smoothed_center))
split_y = y_min + split_idx_relative + window // 2

img_bottom = img_right.crop((0, split_y, img_right.width, h))
img_bottom.save("Sample/page06_right_bottom.jpg")
print("Saved Sample/page06_right_bottom.jpg")
