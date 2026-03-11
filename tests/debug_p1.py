import os
import asyncio
from pathlib import Path
from google import genai
from google.genai import types
from pdf2image import convert_from_path
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('GEMINI_API_KEY')
client = genai.Client(api_key=API_KEY)

# 以前の（詳しい）プロンプトに近いもの
DETAILED_PROMPT = """指示：日本の縦書き書籍（見開き）の高精度テキスト化

1. 読字方向の厳守（最優先）
この画像はPDFからスキャンされた日本語の「縦書き・見開き」レイアウトです。右から左に読んでください。
必ず以下の順序でテキスト化してください：
- まず右のページの、一番右側の行から順に左に向かって（Right-to-Left）下まで読み進める。
- 右ページがすべて終わったら、次に左ページの、一番右側の行から順に左に向かって読む。

2. ノイズの完全排除
以下の要素は除外してください：
- ページ番号
- 書籍のタイトルや章名（ヘッダー・フッター）
- ルビ（親文字のみ抽出）
- 図表
- 文字間の不自然なスペース

3. 段落と改行の扱い
- 物理的な行末での改行は禁止。文章は連結してください。
- 改行を挿入するのは、「段落が切り替わる箇所」および「見出し」の前後のみ。

4. 出力形式
- 本文のみ。
- 最後に [[PAGE_1]] を付与。"""

async def test_ocr():
    # Page 1 の画像を生成
    pdf_path = Path("Sample/hirano.pdf")
    pages = convert_from_path(str(pdf_path), dpi=300, first_page=1, last_page=1)
    img_path = Path("test_p1.jpg")
    pages[0].save(img_path, "JPEG")

    print("Running OCR with gemini-2.5-flash...")
    with open(img_path, "rb") as f:
        image_data = f.read()
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            DETAILED_PROMPT,
            types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
        ],
        config=types.GenerateContentConfig(
            safety_settings=[types.SafetySetting(category=cat, threshold="BLOCK_NONE") for cat in ["HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_DANGEROUS_CONTENT"]]
        )
    )
    
    with open("test_ocr_p1_2.5flash.txt", "w") as f:
        f.write(response.text)
    print("Saved to test_ocr_p1_2.5flash.txt")

if __name__ == "__main__":
    asyncio.run(test_ocr())
