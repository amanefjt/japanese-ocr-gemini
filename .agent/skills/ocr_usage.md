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
    python gemini_ocr_v2.py [path/to/your_file.pdf] --free
    ```
2.  **オプション機能**:
    - `--free`: 無料枠 (15 RPM / 3並列) のレート制限で実行。
    - `--single`: 強制的に単一ページモードで実行。
    - `--spread`: 強制的に見開きモードで実行。
    - `--start`, `--end`: 開始・終了ページを指定。
3.  **シーケンシャル文脈 OCR (V3)**:
    - デフォルトで、前ページの末尾テキストを文脈として提示する高度な抽出が有効になります。
4.  **出力**:
    - `[input_filename]_ocr_v2.txt` が生成されます。

## 注意事項
- **API 制限**: Resource Exhausted (429) エラーが発生した場合は、自動的に指数バックオフリトライを行います。
- **コスト**: Gemini Pro 1.5 または Flash を使用し、文脈提示による精度向上を図っています。
- **依存ライブラリ**: `numpy`, `Pillow`, `pdf2image`, `google-genai`, `aiolimiter`, `python-dotenv` が必要です。
