import os
import time
import asyncio
import argparse
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
import numpy as np
from PIL import Image
from pdf2image import convert_from_path
from google import genai
from google.genai import types
from dotenv import load_dotenv
from aiolimiter import AsyncLimiter

# .env ファイルから環境変数を読み込む
load_dotenv()

# ================= 設定エリア =================
# 環境変数からAPIキーを取得
API_KEY = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')

# 使用するモデル (model_optimization.md に基づく)
MODEL_ID = "gemini-3.1-flash-lite-preview"

# 解像度
DPI = 300

# 処理するページ範囲
START_PAGE = 1
END_PAGE = None 

# ================= プロンプト設定 =================
OCR_PROMPT = """指示：日本語書籍（縦書き一段組）の超高精度テキスト化

あなたは、国立国会図書館のデジタルアーカイブ化プロジェクトに従事するデータ入力エキスパートです。提示された画像（縦書き一段組の本文）をテキスト化してください。

【規則】
1. 文章の連結: 書籍上の物理的な改行位置では絶対に改行せず、行末と次行の行頭を間にスペースを入れずに連結し、一つの文にしてください。
2. 段落の保持: 改行を行うのは、「段落が変わる箇所（通常、文頭が一字下がっている箇所）」のみとしてください。
3. ノイズの除去: ページ番号（ノンブル）、ヘッダー（柱）、フッターは出力から完全に除外してください。
4. ルビ・図表: 本文の流れを阻害しないよう、ルビや図表内の文字は無視してください。

出力は文字修飾のないプレーンテキスト形式とし、挨拶や解説は一切含めないでください。"""

# ================= 1. 画像処理モジュール (SOLID: 単一責任) =================

def extract_images_to_list(pdf_path: Path, temp_dir: Path, dpi: int = 300, split: bool = True) -> list[Path]:
    """PDFを画像化し、必要に応じて物理分割（メモリ保護のためディスク経由）"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] PDF画像変換中 (DPI: {dpi})...")
    
    # メモリ節約のため paths_only=True でディスクに直接書き出す (OOM保護)
    img_paths = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=START_PAGE,
        last_page=END_PAGE,
        output_folder=str(temp_dir),
        fmt="jpeg",
        paths_only=True
    )
    img_paths = sorted([Path(p) for p in img_paths])

    if not split:
        return img_paths

    final_paths = []
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 見開き画像を4分割中 (右上 -> 右下 -> 左上 -> 左下)...")
    
    for i, spread_path in enumerate(img_paths):
        with Image.open(spread_path) as img:
            # Step 0: 画像のNumpy配列化 (グレースケール)
            gray_img = img.convert("L")
            img_array = np.array(gray_img)
            height, width = img_array.shape
            
            # Step 1: ノド（左右）の分割
            # X軸の中央 40%〜60% の範囲を探索
            x_min = int(width * 0.40)
            x_max = int(width * 0.60)
            # 各列のピクセル値の合計を計算 (白い部分ほど値が大きくなる)
            col_sums = np.sum(img_array[:, x_min:x_max], axis=0)
            # 最も白い列のX座標 (元の全体幅における座標に戻す)
            split_x = x_min + np.argmax(col_sums)
            
            # 右ページと左ページの画像を生成
            img_right = img.crop((split_x, 0, width, height))   # 右ページ
            img_left = img.crop((0, 0, split_x, height))      # 左ページ
            
            # Step 2: 段間（上下）の分割を行う関数
            def split_vertical(target_img: Image.Image, side_name: str) -> tuple[Image.Image, Image.Image]:
                arr = np.array(target_img.convert("L"))
                h, w = arr.shape
                # Y軸の中央 40%〜60% の範囲を探索
                y_min = int(h * 0.40)
                y_max = int(h * 0.60)
                # 各行のピクセル値の合計を計算
                row_sums = np.sum(arr[y_min:y_max, :], axis=1)
                # 最も白い行のY座標 (元の全体高さにおける座標に戻す)
                split_y = y_min + np.argmax(row_sums)
                
                # 上段と下段の画像を生成
                img_top = target_img.crop((0, 0, w, split_y))
                img_bottom = target_img.crop((0, split_y, w, h))
                return img_top, img_bottom

            # 右ページを上下に分割
            rt_img, rb_img = split_vertical(img_right, "Right")
            # 左ページを上下に分割
            lt_img, lb_img = split_vertical(img_left, "Left")
            
            # 命名規則と保存 (送信順序に合わせてリストに追加: 1.右ページ上段 -> 2.右下段 -> 3.左上段 -> 4.左下段)
            
            # 1. 右ページ上段
            rt_path = temp_dir / f"{spread_path.stem}_{i:03}_01_RT.jpg"
            rt_img.save(rt_path, "JPEG", quality=95)
            final_paths.append(rt_path)
            
            # 2. 右ページ下段
            rb_path = temp_dir / f"{spread_path.stem}_{i:03}_02_RB.jpg"
            rb_img.save(rb_path, "JPEG", quality=95)
            final_paths.append(rb_path)
            
            # 3. 左ページ上段
            lt_path = temp_dir / f"{spread_path.stem}_{i:03}_03_LT.jpg"
            lt_img.save(lt_path, "JPEG", quality=95)
            final_paths.append(lt_path)
            
            # 4. 左ページ下段
            lb_path = temp_dir / f"{spread_path.stem}_{i:03}_04_LB.jpg"
            lb_img.save(lb_path, "JPEG", quality=95)
            final_paths.append(lb_path)
            
        # 元の見開き画像は削除してディスクスペースを節約
        spread_path.unlink()

    return final_paths

# ================= 2. API通信モジュール (SOLID: 単一責任 + リトライ強化) =================

async def call_gemini_async_with_retry(client, image_path: Path, prompt: str, page_num: int, side: str, limiter: AsyncLimiter):
    """Gemini APIを非同期で呼び出し、詳細なエラー報告とリトライを行う"""
    
    for attempt in range(5):
        try:
            with open(image_path, "rb") as f:
                image_data = f.read()
            
            async with limiter:
                start_time = time.time()
                # aio 経由で非同期実行
                # model_optimization.md の指示に従い thinking_config を設定
                generate_config = types.GenerateContentConfig(
                    temperature=0.0,
                    thinking_config=types.ThinkingConfig(thinking_level="HIGH")
                )
                
                response = await client.aio.models.generate_content(
                    model=MODEL_ID,
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
                    ],
                    config=generate_config
                )
                
                duration = time.time() - start_time
                if response.text:
                    print(f"  [OK] Page {page_num} ({side}): 完了 ({duration:.1f}s)")
                    return response.text
                return ""

        except Exception as e:
            err_msg = str(e)
            # 詳細なエラー種類の判定
            if any(code in err_msg for code in ["429", "RESOURCE_EXHAUSTED"]):
                wait_sec = (2 ** attempt) + 5
                print(f"  [!] Page {page_num} ({side}): レート制限発生。{wait_sec}秒待機してリトライします... ({attempt+1}/5)")
                await asyncio.sleep(wait_sec)
            elif any(code in err_msg for code in ["500", "503", "504"]):
                wait_sec = 2
                print(f"  [!] Page {page_num} ({side}): サーバーエラー({err_msg[:20]}...)。再試行します。")
                await asyncio.sleep(wait_sec)
            else:
                # 致命的なエラー（認証、ファイル不備など）は即座に報告
                print(f"  [x] Page {page_num} ({side}): 致命的なエラー: {e}")
                return f"[[ERROR_PAGE_{page_num}_{side}]]"
    
    print(f"  [x] Page {page_num} ({side}): 全リトライが失敗しました。")
    return f"[[RETRY_FAILED_PAGE_{page_num}_{side}]]"

# ================= 3. メイン制御フロー =================

def parse_args():
    parser = argparse.ArgumentParser(description="Gemini APIを使用した高機能OCR")
    parser.add_argument("input_pdf", nargs='?', help="入力PDFファイルのパス")
    parser.add_argument("--mode", choices=['1', '2'], help="1: 一段組, 2: 二段組(分割あり)")
    return parser.parse_args()

async def main_async():
    args = parse_args()
    
    # パス入力の処理
    input_path_str = args.input_pdf
    if not input_path_str:
        print("PDFファイルのパスを指定してください。")
        input_path_str = input("パス: ").strip()
        if not input_path_str:
            # デフォルトファイル名
            input_path_str = "hirano.pdf"

    input_path = Path(input_path_str).absolute()
    if not input_path.exists():
        print(f"エラー: 指定されたファイルが見つかりません: {input_path}")
        return

    output_path = input_path.with_name(f"{input_path.stem}_ocr.txt")
    
    if not API_KEY:
        print("エラー: APIキーが設定されていません。")
        return
        
    client = genai.Client(api_key=API_KEY)
    
    # レイアウト選択
    mode = args.mode
    if not mode:
        print("\n--- 文書のレイアウトを選択してください ---")
        print("1: 一段組 (分割なし)")
        print("2: 二段組 (自動分割)")
        mode = input("選択 (1 または 2): ").strip()
    
    use_split = (mode == '2')
    
    print(f"\n--- 処理開始: {input_path.name} ---")
    print(f"--- 構成: SOLID + メモリ保護 (非同期リトライ版) ---")
    print(f"--- 出力先: {output_path} ---\n")

    # APIレート制限 (1分間に15リクエスト程度に制限して安定させる)
    limiter = AsyncLimiter(15, 60)

    # 一時ディレクトリで作業 (OOM保護)
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        
        # 1. 画像抽出 (ディスク経由)
        image_paths = extract_images_to_list(input_path, temp_dir, DPI, split=use_split)
        total_items = len(image_paths)
        
        # 2. OCR処理 (非同期)
        with open(output_path, "w", encoding="utf-8") as f:
            for i, img_path in enumerate(image_paths):
                current_num = i + 1
                # 命名規則からどの部分かを判定
                if "_RT.jpg" in img_path.name:
                    side = "右ページ上段"
                elif "_RB.jpg" in img_path.name:
                    side = "右ページ下段"
                elif "_LT.jpg" in img_path.name:
                    side = "左ページ上段"
                elif "_LB.jpg" in img_path.name:
                    side = "左ページ下段"
                else:
                    side = "見開き全体"
                
                print(f"[{current_num}/{total_items}] OCR処理中 ({side})...")
                
                text = await call_gemini_async_with_retry(
                    client, img_path, OCR_PROMPT, current_num, side, limiter
                )
                
                # 右ページ上段または見開き全体の開始時にページヘッダを書き込む
                if "_RT.jpg" in img_path.name or "全体" in side:
                    page_idx = (current_num - 1) // 4 + 1 if use_split else current_num
                    f.write(f"\n\n--- Page Group {page_idx} ---\n")
                
                f.write(text + "\n")
                f.flush()
                
                # 小休止
                await asyncio.sleep(0.05)
        
    print(f"\nすべての処理が完了しました。結果: {output_path}")

if __name__ == '__main__':
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n中断されました。")
    except Exception as e:
        print(f"\n予期せぬエラーが発生しました: {e}")
