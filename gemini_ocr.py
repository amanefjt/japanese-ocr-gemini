import os
import time
import asyncio
import argparse
import tempfile
from pathlib import Path
from datetime import datetime
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

# 使用するモデル (以前の古い設定を維持)
MODEL_ID = "gemini-3-flash-preview"

# 解像度
DPI = 300

# 処理するページ範囲
START_PAGE = 1
END_PAGE = None 

# ================= プロンプト設定 =================
# 以前の古いプロンプトをそのまま維持
OCR_PROMPT = """指示：日本語書籍（縦書き・見開き）の超高精度テキスト化

1. 役割
あなたは、国立国会図書館のデジタルアーカイブ化プロジェクトに従事する、世界最高峰のデータ入力エキスパートです。提示された画像（スキャンされた日本語の縦書き・見開きの{side}部分）を、一文字の妥協もなく、元の文章のレイアウトを完全に維持した状態でテキスト化してください。

2. ドキュメント構造の理解
* **重複の排除（重要）**: 見開き画像の分割処理において、中央部分（ノド）付近の文章が左右の画像で重複している場合があります。この場合、重複部分を検出し、**一度だけ**出力するようにしてください（二重に出力しないこと）。
* **文章の連結（最重要）**: 書籍上の物理的な改行位置では**絶対に改行コードを入れないでください**。行末と次行の行頭は、間にスペースを入れずに連結し、一つの文として続けてください。
* **段落の扱い**: 改行を行うのは、**「段落が変わる箇所（通常、文頭が一字下がっている箇所）」**および「見出し」の前後のみとしてください。

3. 具体的な処理規則
* **文字認識**: 常用漢字、旧字体、ひらがな、カタカナ、句読点を正確に識別してください。
* **ノイズの除去**: ページ番号（ノンブル）、ヘッダー（柱）、フッターは本文の文脈を分断するため、**出力から完全に除外してください**。
* **推論による補完**: スキャンの歪みや綴じ部分の影で文字が不鮮明な場合や明らかなOCRエラーは、前後の文脈から日本語として最も自然な文字を推論して埋めてください。
* **ルビ・図表**: 本文の自然な流れを阻害しないよう、ルビや図表内の文字は読み飛ばしてください。
* **不要な空白の削除**: 文字間の不自然なスペースはすべて削除し、詰めて記述してください。

4. 出力形式
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
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 見開き画像を左右に分割中 (5% 重複クロップ)...")
    
    for i, spread_path in enumerate(img_paths):
        with Image.open(spread_path) as img:
            width, height = img.size
            margin = int(width * 0.05)
            center = width // 2

            # 右側
            right_img = img.crop((center - margin, 0, width, height))
            r_path = temp_dir / f"{spread_path.stem}_{i:03}_R.jpg"
            right_img.save(r_path, "JPEG", quality=95)
            final_paths.append(r_path)

            # 左側
            left_img = img.crop((0, 0, center + margin, height))
            l_path = temp_dir / f"{spread_path.stem}_{i:03}_L.jpg"
            left_img.save(l_path, "JPEG", quality=95)
            final_paths.append(l_path)
        
        # 元の画像は削除してディスクスペースを節約
        spread_path.unlink()

    return final_paths

# ================= 2. API通信モジュール (SOLID: 単一責任 + リトライ強化) =================

async def call_gemini_async_with_retry(client, image_path: Path, prompt: str, page_num: int, side: str, limiter: AsyncLimiter):
    """Gemini APIを非同期で呼び出し、詳細なエラー報告とリトライを行う"""
    
    formatted_prompt = prompt.replace("{side}", side)

    for attempt in range(5):
        try:
            with open(image_path, "rb") as f:
                image_data = f.read()
            
            async with limiter:
                start_time = time.time()
                # aio 経由で非同期実行
                response = await client.aio.models.generate_content(
                    model=MODEL_ID,
                    contents=[
                        formatted_prompt,
                        types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
                    ],
                    config=types.GenerateContentConfig(temperature=0.0)
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
    
    # パス入力の処理 (古いコードの挙動を維持)
    input_path_str = args.input_pdf
    if not input_path_str:
        print("PDFファイルのパスを指定してください。 (tobeocr.pdf を探す場合はそのままエンター)")
        input_path_str = input("パス: ").strip() or "tobeocr.pdf"
    
    input_path = Path(input_path_str).absolute()
    if not input_path.exists():
        print(f"エラー: ファイルが見つかりません: {input_path}")
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
    print(f"--- 構成: {'SOLID + メモリ保護 (非同期リトライ版)'} ---")
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
                side = "右側" if "_R.jpg" in img_path.name else ("左側" if "_L.jpg" in img_path.name else "見開き全体")
                
                print(f"[{current_num}/{total_items}] OCR処理中 ({side})...")
                
                text = await call_gemini_async_with_retry(
                    client, img_path, OCR_PROMPT, current_num, side, limiter
                )
                
                # 結果を即座に書き出し
                if "_R" in img_path.name or "全体" in side:
                    f.write(f"\n\n--- Page Group {current_num // 2 + 1 if use_split else current_num} ---\n")
                
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