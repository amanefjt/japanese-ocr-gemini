# OCR ツールの使用方法 (ocr_usage.md)

## 概要
Google Gemini API (Gemini 3 Flash) を使用して、PDF ファイルから高精度なテキスト抽出を行う Python ツール (`gemini_ocr.py`) の実行方法を定義します。

## セットアップ
1.  **依存ライブラリのインストール**:
    ```bash
    pip install google-genai pdf2image python-dotenv
    ```
2.  **poppler のインストール (macOS)**:
    ```bash
    brew install poppler
    ```
3.  **環境変数の設定**:
    `.env` ファイルを作成し、Gemini API キーを設定します。
    ```text
    GEMINI_API_KEY=your_api_key_here
    ```

## 実行手順
1.  **コマンドライン引数で実行**:
    ```bash
    python gemini_ocr.py [path/to/your_file.pdf]
    ```
    引数を省略した場合は、実行時に入力を求められます。
2.  **レイアウトの選択**:
    実行中に、以下の 2 つのモードから選択します。
    - `1`: 一段組 (見開き全体の OCR)
    - `2`: 二段組 (左右に分割して OCR)
3.  **出力**:
    入力ファイルと同じディレクトリに `[input_filename]_ocr.txt` が生成されます。

## 注意事項
- **API 制限**: Resource Exhausted (429) エラーが発生した場合は、スクリプトが自動的にリトライします。
- **コスト**: Gemini 3 Flash を使用しているため、コスト効率と精度のバランスが取れています。
