import asyncio
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv
from models import OCRConfig
from processor.ocr_orchestrator import OCROrchestrator

def parse_args():
    parser = argparse.ArgumentParser(description="Gemini APIを使用した高機能OCR (Modular Version)")
    parser.add_argument("input_pdf", nargs="?", help="入力PDFファイルのパス")
    parser.add_argument("--free", action="store_true", help="無料枠制限 (15 RPM) で実行する")
    parser.add_argument("--single", action="store_true", help="強制的に単一ページモードで実行する")
    parser.add_argument("--spread", action="store_true", help="強制的に見開きモードで実行する")
    parser.add_argument("--start", type=int, default=1, help="開始ページ (1開始)")
    parser.add_argument("--end", type=int, help="終了ページ (省略時は最後まで)")
    parser.add_argument(
        "--parallel-pool", action="store_true",
        help="[実験的・非推奨] 無料枠Liteプール(2モデル)へページペア単位でラウンドロビン発行し並列実行する。"
             "約30%%高速化するが、実地検証で段落の重複・欠落や誤字（gemini-3.5-flash-liteの"
             "「社会理論」→「社会会理論」等）を確認済み。精度が最優先の場合は使用しないこと。"
    )
    return parser.parse_args()

async def main():
    load_dotenv()
    args = parse_args()

    input_path_str = args.input_pdf
    if not input_path_str:
        print("PDFファイルのパスを指定してください。")
        input_path_str = input("パス: ").strip() or "tobeocr.pdf"

    input_path = Path(input_path_str).absolute()
    if not input_path.exists():
        print(f"エラー: ファイルが見つかりません: {input_path}")
        return

    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not api_key:
        print("エラー: APIキーが設定されていません。")
        return

    # 設定の初期化
    config = OCRConfig.from_args(args, api_key)
    
    # オーケストレーターの実行
    orchestrator = OCROrchestrator(config)
    
    output_path = input_path.with_name(f"{input_path.stem}_ocr_v2.txt")
    
    await orchestrator.run(
        input_pdf=input_path,
        output_txt=output_path,
        force_single=args.single,
        force_spread=args.spread
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n中断されました。")
    except Exception as e:
        print(f"\n予期せぬエラーが発生しました: {e}")
