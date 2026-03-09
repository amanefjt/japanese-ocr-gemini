import os
import time
import argparse
import tempfile
import shutil
from pathlib import Path
from typing import Generator
from google import genai
from pdf2image import convert_from_path
from dotenv import load_dotenv

# .env ファイルから環境変数を読み込む
load_dotenv()

# ================= 設定エリア =================
API_KEY = os.getenv('GEMINI_API_KEY')
MODEL_ID = "gemini-3-flash-preview"  # 最新の Gemini 3 Flash を使用
DPI = 300
# ============================================

OCR_PROMPT = """指示：日本古来の縦書き書籍（見開き）の高精度テキスト化

1. 読字方向の厳守（最優先）
この画像は日本語の「縦書き・見開き」レイアウトです。絶対に横方向（左から右）に読まないでください。
必ず以下の順序でテキスト化してください：
- まず右のページの、一番右側の行から順に左に向かって（Right-to-Left）下まで読み進める。
- 右ページがすべて終わったら、次に左ページの、一番右側の行から順に左に向かって読む。

2. ノイズの完全排除
以下の要素は本文の文脈を破壊するため、出力から完全に除外してください：
- 各ページの上部・下部にあるページ番号（例：169、170）
- 書籍のタイトルや章名（例：食のフィールドワーカー）などの柱（ヘッダー・フッター）

3. 段落と改行の扱い
- 物理的な行末での改行は禁止です。文章は一つの連続した文として連結してください。
- 改行を挿入するのは、「段落が切り替わる箇所」および「見出し」の前後のみとしてください。

4. 出力形式
- 出力は純粋なMarkdown形式とし、挨拶や解説、画像に関する説明は一切含めないでください。"""

def extract_images_safely(pdf_path: Path, dpi: int = 300) -> Generator[Path, None, None]:
    """
    PDFから1ページずつ画像を抽出し、一時ファイルのパスを返すジェネレータ。
    OOM対策のため、一括でメモリに保持せずディスクを介在させる。
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        # pdf2imageのconvert_from_pathでoutput_folderを指定するとメモリ消費を抑えられる
        # 画像は一時ディレクトリに保存される
        convert_from_path(
            str(pdf_path),
            dpi=dpi,
            output_folder=str(temp_dir_path),
            fmt="jpeg",
            paths_only=True
        )
        
        # 保存されたファイルを順番に処理（ファイル名は自動生成されるためソートが必要）
        image_files = sorted(temp_dir_path.glob("*.jpg"))
        
        for img_path in image_files:
            yield img_path
            # 次のページに進む前に現在の画像ファイルを削除（TemporaryDirectoryが最後に行うが、念のため早期解放）
            if img_path.exists():
                img_path.unlink()

def call_gemini_with_retry(client: genai.Client, image_path: Path, prompt: str, max_retries: int = 5) -> str:
    """
    Gemini APIを呼び出し、指数的バックオフを伴うリトライを行う。
    """
    for attempt in range(max_retries):
        try:
            # 画像ファイルを読み込む
            with open(image_path, "rb") as f:
                image_data = f.read()
            
            # API呼び出し
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=[
                    prompt,
                    genai.types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
                ]
            )
            
            if response.text:
                return response.text
            return ""

        except Exception as e:
            err_msg = str(e)
            # 429 (RESOURCE_EXHAUSTED) や 503 (SERVICE_UNAVAILABLE) の場合にリトライ
            if any(code in err_msg for code in ["429", "RESOURCE_EXHAUSTED", "503", "500"]):
                wait_sec = (2 ** attempt) + 5  # 少し長めに待機: 7, 9, 13, 21, 37...
                print(f"  [!] API制限または一時的エラー: {err_msg}...")
                print(f"      {wait_sec}秒待機してリトライします... ({attempt+1}/{max_retries})")
                time.sleep(wait_sec)
            else:
                print(f"  [x] 致命的なエラー: {e}")
                raise e
    
    print(f"  [x] 最大リトライ回数({max_retries})に達しました。")
    return ""

def parse_args():
    """
    コマンドライン引数と対話型入力を処理する。
    """
    parser = argparse.ArgumentParser(description='Gemini APIを使用した高精度OCRツール')
    parser.add_argument('input_path', nargs='?', default=None, help='OCR対象のPDFファイルパス')
    args = parser.parse_args()

    input_path_str = args.input_path
    
    # 引数がない場合は入力を求める
    if not input_path_str:
        print("PDFファイルのパスを指定してください。")
        input_path_str = input("パス: ").strip()
        if not input_path_str:
            # デフォルトファイル名（もしあれば）
            input_path_str = "hirano.pdf"  # ユーザー指定のテストファイル

    input_path = Path(input_path_str).absolute()
    
    if not input_path.exists():
        print(f"エラー: 指定されたファイルが見つかりません: {input_path}")
        return None, None

    # 出力ファイルを入力ファイルと同じディレクトリに設定
    output_path = input_path.with_name(f"{input_path.stem}_ocr.txt")
    
    return input_path, output_path

def process_pdf(input_path: Path, output_path: Path):
    """
    OCR全体処理のメインパイプライン。
    """
    if not API_KEY:
        print("エラー: GEMINI_API_KEY が設定されていません。")
        return

    client = genai.Client(api_key=API_KEY)
    
    print(f"--- 高精度OCR処理開始: {input_path.name} ---")
    print(f"--- 使用モデル: {MODEL_ID} ---")
    
    # 画像抽出（ジェネレータ）
    image_generator = extract_images_safely(input_path, dpi=DPI)
    
    # 出力ファイルを 'w' モードでオープンし、1ページごとに flush する
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, img_path in enumerate(image_generator):
            page_num = i + 1
            print(f"[{page_num}] ページ処理中...")
            
            try:
                # Gemini呼び出し
                text = call_gemini_with_retry(client, img_path, OCR_PROMPT)
                
                if text:
                    # ページ区切りとテキストの書き出し
                    f.write(f"\n\n--- Page {page_num} ---\n")
                    f.write(text + "\n")
                    f.flush()
                    print(f"[{page_num}] 完了")
                else:
                    print(f"[{page_num}] スキップ（テキスト取得失敗）")
                    
            except Exception as e:
                print(f"[{page_num}] ページ処理中にエラーが発生しました: {e}")
                continue

    print(f"\nすべての処理が完了しました。結果は「{output_path}」に保存されています。")

if __name__ == '__main__':
    in_p, out_p = parse_args()
    if in_p and out_p:
        process_pdf(in_p, out_p)