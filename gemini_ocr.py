import os
import time
import argparse
from pathlib import Path
from google import genai
from pdf2image import convert_from_path
from dotenv import load_dotenv

# .env ファイルから環境変数を読み込む
load_dotenv()

# ================= 設定エリア =================
# 環境変数からAPIキーを取得 (設定されていない場合は None)
API_KEY = os.getenv('GEMINI_API_KEY')
# デフォルトのファイル名（カレントディレクトリに存在する場合）
DEFAULT_PDF_NAME = 'tobeocr.pdf'

# 3 Flash を指定（推奨）
MODEL_ID = "gemini-3-flash-preview"

# 解像度 (300DPIがOCR精度とコストのバランスが最適です)
DPI = 300

# 処理するページ範囲
START_PAGE = 1
END_PAGE = None 

# 基本待機時間
WAIT_TIME = 0.1
# ============================================

# 高精度プロンプト（ハードコード済み）
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
出力は純粋なMarkdown形式とし、挨拶や解説は一切含めないでください。"""

def run_ultimate_ocr():
    # 引数処理
    parser = argparse.ArgumentParser(description='Gemini APIを使用した高精度OCRツール')
    parser.add_argument('input_path', nargs='?', default=None, help='OCR対象のPDFファイルパス')
    args = parser.parse_args()

    input_path_str = args.input_path
    
    # 引数がない場合は入力を求める
    if not input_path_str:
        print("PDFファイルのパスを指定してください。")
        print(f"何も入力せずにエンターを押すと、現在のフォルダの '{DEFAULT_PDF_NAME}' を探します。")
        input_path_str = input("パス: ").strip()
        if not input_path_str:
            input_path_str = DEFAULT_PDF_NAME

    input_path = Path(input_path_str).absolute()
    
    if not input_path.exists():
        print(f"エラー: 指定されたファイルが見つかりません: {input_path}")
        return

    # 出力ファイルを入力ファイルと同じディレクトリに設定
    output_path = input_path.with_name(f"{input_path.stem}_ocr.txt")

    if not API_KEY:
        print("エラー: GEMINI_API_KEY が .env ファイルまたは環境変数に設定されていません。")
        return

    client = genai.Client(api_key=API_KEY)
    
    print(f"--- 高精度OCR処理開始: {input_path} ---")
    print(f"--- 出力先: {output_path} ---")
    print(f"--- 使用モデル: {MODEL_ID} ---")

    try:
        # PDFを画像に変換
        print("PDFを読み込んでいます...")
        images = convert_from_path(str(input_path), dpi=DPI, first_page=START_PAGE, last_page=END_PAGE)
    except Exception as e:
        print(f"PDF読み込みエラー: {e}")
        return

    # レイアウト選択
    print("\n--- 文書のレイアウトを選択してください ---")
    print("1: 一段組 (分割なし) - 絵本や一般書など、見開き全体で処理します")
    print("2: 二段組 (自動分割) - 論文や小説など、左右に分割して処理します")
    
    while True:
        layout_choice = input("選択 (1 または 2): ").strip()
        if layout_choice in ['1', '2']:
            break
        print("1 か 2 を入力してください。")

    print(f"\n処理を開始します... (全{len(images)}ページ)\n")

    # モード 'a' で追記（既存のファイルを上書きしたくない場合は 'a'、毎回新しくしたい場合は 'w'）
    # ユーザーの「同じ場所に結果を出力」という要望に合わせ、上書き/新規作成（'w'）を選択
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, image in enumerate(images):
            current_page_num = START_PAGE + i
            print(f"[{current_page_num}/{START_PAGE + len(images) - 1}] ページ処理中...")
            
            width, height = image.size
            parts = []

            if layout_choice == '2':
                # === 二段組（自動分割） ===
                margin = int(width * 0.05) # 中央の重なり部分（5%）
                center = width // 2
                
                # 右側
                parts.append({
                    "name": "右側", 
                    "img": image.crop((center - margin, 0, width, height))
                })
                # 左側
                parts.append({
                    "name": "左側", 
                    "img": image.crop((0, 0, center + margin, height))
                })
            else:
                # === 一段組（分割なし） ===
                parts.append({
                    "name": "見開き全体", 
                    "img": image
                })
            
            f.write(f"\n\n--- Page {current_page_num} ---\n")

            for part in parts:
                side = part["name"]
                cropped_img = part["img"]
                
                prompt = OCR_PROMPT.replace("{side}", side)
 
                success = False
                max_retries = 5
                
                for attempt in range(max_retries):
                    try:
                        response = client.models.generate_content(
                            model=MODEL_ID, 
                            contents=[prompt, cropped_img]
                        )
                        
                        if response.text:
                            f.write(response.text + "\n")
                            f.flush()
                            success = True
                        break 

                    except Exception as e:
                        err_msg = str(e)
                        if any(code in err_msg for code in ["429", "RESOURCE_EXHAUSTED", "503"]):
                            wait_sec = 5 * (attempt + 1)
                            print(f"  [!] API制限発生 ({side})。{wait_sec}秒待機してリトライします... ({attempt+1}/{max_retries})")
                            time.sleep(wait_sec)
                        else:
                            print(f"  [x] エラー ({side}): {e}")
                            break 
                
                if not success:
                    print(f"  [x] {side} の処理に失敗しました。")

                time.sleep(WAIT_TIME)

            print(f"[{current_page_num}] 完了")

    print(f"\nすべての処理が完了しました。結果は「{output_path}」に保存されています。")

if __name__ == '__main__':
    run_ultimate_ocr()