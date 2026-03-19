import os
import re
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
OCR_PROMPT_STRUCTURED = """指示：日本語書籍（縦書き二段組の分割画像）の超高精度テキスト化

あなたは、国立国会図書館のデジタルアーカイブ化プロジェクトに従事するデータ入力エキスパートです。提示された画像（縦書き二段組の一部）をテキスト化してください。

【規則】
1. 文章の連結: 書籍上の物理的な改行位置では絶対に改行せず、行末と次行の行頭を間にスペースを入れずに連結し、一つの文にしてください。
2. 段落の保持: 改行を行うのは、「段落が変わる箇所（通常、文頭が一字下がっている箇所）」のみとしてください。
3. ノイズの除去: ページ番号（ノンブル）、ヘッダー（柱）、フッターは出力から完全に除外してください。
4. ルビ・図表: 本文の流れを阻害しないよう、ルビや図表内の文字は無視してください。

出力は文字修飾のないプレーンテキスト形式とし、挨拶や解説は一切含めないでください。"""

OCR_PROMPT_RELAXED = """指示：日本語書籍（縦書き一段組・扉絵など）の超高精度テキスト化

あなたは、国立国会図書館のデジタルアーカイブ化プロジェクトに従事するデータ入力エキスパートです。提示された画像をテキスト化してください。

【規則】
1. 文章の連結: 同一段落内の物理的な改行では改行せず、行末と次行の行頭を連結してください。
2. 段落・見出しの保持: タイトル、章名、著者名など明らかに独立した要素はそれぞれ独立した行として出力してください。
3. ノイズの除去: ページ番号（ノンブル）、ヘッダー（柱）、フッターは出力から完全に除外してください。
4. ルビ・図表: 本文の流れを阻害しないよう、ルビや図表内の文字は無視してください。

出力は文字修飾のないプレーンテキスト形式とし、挨拶や解説は一切含めないでください。"""

# ================= 1. 画像処理モジュール =================
TWO_COLUMN_THRESHOLD = 0.2  # 修正: 最も黒要素が少ない行が、平均黒要素の20%未満なら段間として判定する

def find_gutter_x(img_array: np.ndarray) -> tuple[int, bool]:
    """
    見開き画像のノド（綴じ目）のX座標を検出する。
    幅の40%〜60%の範囲で、最もインクが少ない（白い）列を探す。
    戻り値: (split_x, is_reliable)
    """
    height, width = img_array.shape
    x_min = int(width * 0.40)
    x_max = int(width * 0.60)
    
    # 列ごとの輝度合計（白=高, 黒=低）
    col_sums = np.sum(img_array[:, x_min:x_max], axis=0).astype(float)
    
    # 移動平均でノイズ除去
    window = 20
    if len(col_sums) > window:
        smoothed = np.convolve(col_sums, np.ones(window)/window, mode='valid')
        relative_idx = np.argmax(smoothed)
        max_val = smoothed.max()
        split_x = x_min + int(relative_idx) + window // 2
    else:
        relative_idx = np.argmax(col_sums)
        max_val = col_sums.max()
        split_x = x_min + int(relative_idx)

    # 信頼性判定: 最も白い列が平均より十分に白いか (1.1倍以上)
    avg_val = col_sums.mean()
    # 隙間（白）が平均より明らかに明るい場合を「信頼できるノド」とする
    is_reliable = (max_val > avg_val * 1.1) and (avg_val < 250 * height)
    
    return split_x, is_reliable


def split_vertical_or_full(
    page_img: Image.Image,
    page_stem: str,
    side_label: str,
    out_dir: Path,
    threshold: float = TWO_COLUMN_THRESHOLD,
) -> tuple[list[Path], str]:
    """
    1ページ画像を受け取り、二段組か一段組かを自動判定して分割する。
    判定は黒文字の密度を用いて行う（反転画像で計算）。
    """
    # 背景白の影響を排除するため、白黒を反転 (黒文字要素>0, 白背景=0)
    img_gray = page_img.convert("L")
    img_array = np.array(img_gray)
    arr = np.invert(img_array)
    h, w = arr.shape

    # Y軸の中央35%〜65%、X軸の中央40%〜60%（傾き対策）を探索範囲とする
    y_min = int(h * 0.35)
    y_max = int(h * 0.65)
    w_min = int(w * 0.40)
    w_max = int(w * 0.60)
    
    center_row_sums = np.sum(arr[y_min:y_max, w_min:w_max], axis=1).astype(float)

    # 移動平均をかけて行間・文字間の細かいギャップを埋め、本当の段間を際立たせる
    window = 30
    if len(center_row_sums) >= window:
        smoothed_center = np.convolve(center_row_sums, np.ones(window)/window, mode='valid')
        split_idx_relative = int(np.argmin(smoothed_center))
        split_y = y_min + split_idx_relative + window // 2
        inv_min = smoothed_center.min()
    else:
        split_idx_relative = int(np.argmin(center_row_sums))
        split_y = y_min + split_idx_relative
        inv_min = center_row_sums.min()

    # 段間(ギャップ)の位置を特定 
    split_idx = split_idx_relative + (window // 2 if len(center_row_sums) >= window else 0)
    
    # 段間（最小値の行）の上下それぞれで平均の文字密度を計算
    top_avg = center_row_sums[:split_idx].mean() if split_idx > 0 else 0
    bottom_avg = center_row_sums[split_idx:].mean() if split_idx < len(center_row_sums) else 0

    inv_avg = center_row_sums.mean()

    # 二段組の条件:
    # 1. 段間として十分に空白の行が存在する (全体の平均の20%以下)
    # 2. 段間の上にある行（上段）に有意な文字群が存在する (全体の平均の30%以上)
    # 3. 段間の下にある行（下段）に有意な文字群が存在する (全体の平均の30%以上)
    # これにより「上半分が完全に空白」などレイアウトが特殊な章末ページは一段組(Full)として1枚で処理する
    is_two_column = (
        inv_min < inv_avg * TWO_COLUMN_THRESHOLD and
        top_avg > inv_avg * 0.3 and
        bottom_avg > inv_avg * 0.3
    )

    paths = []
    if is_two_column:
        img_top = page_img.crop((0, 0, w, split_y))
        img_bottom = page_img.crop((0, split_y, w, h))
 
        top_path = out_dir / f"{page_stem}_{side_label}_Top.jpg"
        bot_path = out_dir / f"{page_stem}_{side_label}_Bottom.jpg"
        img_top.save(top_path, "JPEG", quality=95)
        img_bottom.save(bot_path, "JPEG", quality=95)
        paths = [top_path, bot_path]
        label = "二段組（上下分割）"
    else:
        full_path = out_dir / f"{page_stem}_{side_label}_Full.jpg"
        page_img.save(full_path, "JPEG", quality=95)
        paths = [full_path]
        label = "一段組（分割なし）"

    return paths, label


def extract_images_to_list(pdf_path: Path, temp_dir: Path, dpi: int, 
                          force_single: bool = False,
                          force_spread: bool = False,
                          start_page: int = 1,
                          end_page: int | None = None) -> list[Path]:
    """
    PDFを画像化し、各見開きを以下の手順で処理する:
      Step1: アスペクト比とノド検出で右ページ・左ページに分割するか判定
      Step2: 各ページで二段組/一段組を自動判定し分割
    読み順: 右Top -> 右Bottom -> 左Top -> 左Bottom
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] PDF画像変換中 (DPI: {dpi}, Pages: {start_page}-{end_page or 'End'})...")

    img_paths = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=start_page,
        last_page=end_page,
        output_folder=str(temp_dir),
        fmt="jpeg",
        paths_only=True,
    )
    img_paths = sorted([Path(p) for p in img_paths])

    final_paths = []
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 見開き分割・レイアウト自動判定を開始...")

    for i, spread_path in enumerate(img_paths):
        with Image.open(spread_path) as img:
            img_array = np.array(img.convert("L"))
            height, width = img_array.shape
            
            # アスペクト比による判定 (修正: 1.1以上なら見開き候補とする)
            is_spread_aspect = (width / height > 1.1)
            
            do_split = False
            split_x = width // 2
            
            # force_spread が True ならアスペクト比を無視
            # ただし force_single が優先
            if not force_single and (is_spread_aspect or force_spread):
                # --- Step 1: ノドで左右分割 ---
                split_x, is_reliable = find_gutter_x(img_array)
                if is_reliable:
                    do_split = True
                else:
                    msg = "アスペクト比で見開きと判定されましたが、" if is_spread_aspect else "--spread 指定されましたが、"
                    print(f"  見開き {i+1:03}: [安全策] {msg}明確なノドが不鮮明なため、文字断裁を防ぐため分割をスキップします。")
            
            stem = spread_path.stem
            
            if do_split:
                img_right = img.crop((split_x, 0, width, height))
                img_left = img.crop((0, 0, split_x, height))
                
                # --- Step 2: 右・左ページの順で段組分割 ---
                r_paths, r_label = split_vertical_or_full(img_right, stem, "R", temp_dir)
                l_paths, l_label = split_vertical_or_full(img_left, stem, "L", temp_dir)
                print(f"  見開き {i+1:03}: 右={r_label}, 左={l_label}")
                final_paths.extend(r_paths)
                final_paths.extend(l_paths)
            else:
                # 単一ページとして処理
                paths, label = split_vertical_or_full(img, stem, "F", temp_dir)
                print(f"  ページ {i+1:03}: {label} (単一ページ扱い)")
                final_paths.extend(paths)

        spread_path.unlink()  # ディスク節約

    return final_paths


# ================= 2. API通信モジュール (SOLID: 単一責任 + リトライ強化) =================

async def call_gemini_async_with_retry(client, image_path: Path, prompt: str, page_num: int, side: str, limiter: AsyncLimiter):
    """Gemini APIを非同期で呼び出し、詳細なエラー報告とリトライを行う（ストリーミングでTTFTを計測）"""
    
    for attempt in range(5):
        try:
            with open(image_path, "rb") as f:
                image_data = f.read()
            
            async with limiter:
                start_time = time.time()
                first_token_time = None
                full_text = []
                
                generate_config = types.GenerateContentConfig(
                    temperature=0.0,
                    thinking_config=types.ThinkingConfig(thinking_level="LOW")
                )
                
                # ストリーミングでTTFTを計測しつつ全体を取得
                stream = await client.aio.models.generate_content_stream(
                    model=MODEL_ID,
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
                    ],
                    config=generate_config
                )
                
                async for chunk in stream:
                    if first_token_time is None:
                        first_token_time = time.time()
                    if chunk.text:
                        full_text.append(chunk.text)
                
                end_time = float(time.time())
                ttft_val = (first_token_time - start_time) if isinstance(first_token_time, float) else 0.0
                duration_val = end_time - start_time
                
                usage = ""
                if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                    m = chunk.usage_metadata
                    usage = f" [Tokens: In={m.prompt_token_count}, Out={m.candidates_token_count}]"

                final_text = "".join(full_text)
                if final_text:
                    print(f"  [OK] Page {page_num:02} ({side}): TTFT={ttft_val:.2f}s, Total={duration_val:.1f}s{usage}")
                    return final_text
                return ""

        except Exception as e:
            err_msg = str(e)
            if any(code in err_msg for code in ["429", "RESOURCE_EXHAUSTED"]):
                # エラーメッセージから待機秒数を探す (例: "retry in 10s" or "after 10s")
                match = re.search(r'(?:retry in |after )(\d+)', err_msg)
                if match:
                    wait_sec = int(match.group(1)) + 1
                    print(f"  [!] Page {page_num} ({side}): クォータ制限。API指示に従い {wait_sec}秒待機...")
                else:
                    wait_sec = (2 ** attempt) + 10
                    print(f"  [!] Page {page_num} ({side}): レート制限 (429)。{wait_sec}秒待機... ({attempt+1}/5)")
                await asyncio.sleep(wait_sec)
            elif any(code in err_msg for code in ["500", "503", "504"]):
                wait_sec = 5
                print(f"  [!] Page {page_num} ({side}): サーバーエラー({err_msg[:20]}...)。{wait_sec}秒後に再試行")
                await asyncio.sleep(wait_sec)
            else:
                print(f"  [x] Page {page_num} ({side}): 致命的なエラー: {e}")
                return f"[[ERROR_PAGE_{page_num}_{side}]]"
    
    print(f"  [x] Page {page_num} ({side}): 全リトライが失敗しました。")
    return f"[[RETRY_FAILED_PAGE_{page_num}_{side}]]"

# ================= 3. ファイル名パーサー =================

def parse_side_label(img_path: Path) -> tuple[str, bool]:
    """
    ファイル名のサフィックスから表示用ラベルと「右ページTop/Full」フラグを返す。
    フラグが True のときにページグループヘッダを出力する。
    """
    name = img_path.name
    if "_R_Top" in name:
        return "右ページ上段（二段組）", True
    elif "_R_Bottom" in name:
        return "右ページ下段（二段組）", False
    elif "_R_Full" in name:
        return "右ページ（一段組）", True
    elif "_L_Top" in name:
        return "左ページ上段（二段組）", False
    elif "_L_Bottom" in name:
        return "左ページ下段（二段組）", False
    elif "_L_Full" in name:
        return "左ページ（一段組）", False
    elif "_F_Top" in name:
        return "上段（単一ページ二段組）", True
    elif "_F_Bottom" in name:
        return "下段（単一ページ二段組）", False
    elif "_F_Full" in name:
        return "（単一ページ一段組）", True
    else:
        return "不明", True


# ================= 4. メイン制御フロー =================

def parse_args():
    parser = argparse.ArgumentParser(description="Gemini APIを使用した高機能OCR（レイアウト全自動判定版）")
    parser.add_argument("input_pdf", nargs="?", help="入力PDFファイルのパス")
    parser.add_argument("--free", action="store_true", help="無料枠制限 (15 RPM) で実行する（デフォルトは有料版想定の高速モード）")
    parser.add_argument("--single", action="store_true", help="強制的に単一ページモード（分割なし）で実行する")
    parser.add_argument("--spread", action="store_true", help="強制的に見開きモード（分割あり）で実行する")
    parser.add_argument("--start", type=int, default=1, help="開始ページ (1開始)")
    parser.add_argument("--end", type=int, help="終了ページ (省略時は最後まで)")
    return parser.parse_args()


async def main_async():
    args = parse_args()

    input_path_str = args.input_pdf
    if not input_path_str:
        print("PDFファイルのパスを指定してください。（未入力でデフォルト: tobeocr.pdf）")
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

    # ティアに応じたレート制限設定
    if args.free:
        rpm_limit = 15
        concurrency = 3
        tier_label = "無料枠 (Standard)"
    else:
        # 有料版 (Tier 2/3) 想定: 3.1 Flash Lite は 4,000 RPM だが、安全のため 2,000 に設定
        rpm_limit = 2000
        concurrency = 20
        tier_label = "有料版 (Paid/Pro) 高速モード"

    print(f"\n--- 処理開始: {input_path.name} ---")
    print(f"--- モード: レイアウト全自動判定（二段組閾値={TWO_COLUMN_THRESHOLD}） ---")
    print(f"--- ティア: {tier_label} (同時実行: {concurrency}, 制限: {rpm_limit} RPM) ---")
    print(f"--- 出力先: {output_path} ---\n")

    # レート制限
    limiter = AsyncLimiter(rpm_limit, 60)

    # OOM保護のため一時ディレクトリで作業
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)

        image_paths = extract_images_to_list(input_path, temp_dir, DPI, 
                                            force_single=args.single,
                                            force_spread=args.spread,
                                            start_page=args.start,
                                            end_page=args.end)
        total_items = int(len(image_paths))
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] OCR処理開始: 計{total_items}画像を並行処理\n")

        # 同時実行数を制限するセマフォ
        sem = asyncio.Semaphore(concurrency)

        async def sem_task(img_p, prompt, num, label):
            async with sem:
                return await call_gemini_async_with_retry(
                    client, img_p, prompt, num, label, limiter
                )

        # 全タスクを生成
        tasks = []
        for i, img_path in enumerate(image_paths):
            side_label, _ = parse_side_label(img_path)
            is_two_col = "二段組" in side_label
            current_prompt = OCR_PROMPT_STRUCTURED if is_two_col else OCR_PROMPT_RELAXED
            tasks.append(sem_task(img_path, current_prompt, i + 1, side_label))

        # 並列実行して結果を待機
        results = await asyncio.gather(*tasks)

        # 順序通りにファイル書き出し
        page_group_count: int = 0
        with open(output_path, "w", encoding="utf-8") as f:
            for i, (img_path, text) in enumerate(zip(image_paths, results)):
                _, is_group_start = parse_side_label(img_path)
                if is_group_start:
                    page_group_count += 1
                    f.write(f"\n\n--- Page Group {page_group_count} ---\n")
                f.write(text + "\n")
                f.flush()

    print(f"\n[完了] 結果: {output_path}")

if __name__ == '__main__':
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n中断されました。")
    except Exception as e:
        print(f"\n予期せぬエラーが発生しました: {e}")
