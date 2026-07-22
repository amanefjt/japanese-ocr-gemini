from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

@dataclass(frozen=True)
class OCRConfig:
    """OCR実行の設定を保持するクラス"""
    api_key: str
    model_id: str = "gemini-3.1-flash-lite"
    dpi: int = 300
    start_page: int = 1
    end_page: Optional[int] = None
    is_free_tier: bool = False
    concurrency: int = 20
    rpm_limit: int = 2000
    two_column_threshold: float = 0.2
    # 実験的機能(非推奨): 無料枠Liteプール(2モデル)へページペア単位でラウンドロビン発行し、
    # 各モデル専用のレートリミッタで並列実行することで速度を上げる。既定はOFF(安全側)。
    # 実地検証(2026-07-22, matsumura.pdf 5p/18ユニット)で約30%高速化(103.0s→70.2s)を確認したが、
    # 同時に段落の重複・欠落・誤字(gemini-3.5-flash-liteの「社会理論」→「社会会理論」等)も
    # 確認された。ペア内の2ユニットが同じ(直前ではなく1つ古い)文脈を共有するため、文の継ぎ目で
    # 内容が重複/欠落しうる。翻訳のトーン差程度で済んだp2workflowyより、文字単位の精度が
    # 生命線であるOCRでは実害が大きい。精度優先なら使わないこと。
    parallel_pool: bool = False

    @classmethod
    def from_args(cls, args, api_key: str):
        parallel_pool = getattr(args, "parallel_pool", False)
        if args.free:
            return cls(
                api_key=api_key,
                is_free_tier=True,
                concurrency=3,
                rpm_limit=15,
                start_page=args.start,
                end_page=args.end,
                parallel_pool=parallel_pool
            )
        return cls(
            api_key=api_key,
            start_page=args.start,
            end_page=args.end,
            parallel_pool=parallel_pool
        )

@dataclass(frozen=True)
class ProcessingUnit:
    """処理単位（画像1枚）を表すクラス"""
    image_path: Path
    page_num: int
    side_label: str
    is_two_column: bool
    is_group_start: bool = False
    prompt: str = ""
    prev_context: str = ""  # 前ページの末尾テキスト（文脈用）

@dataclass
class OCRResult:
    """OCRの実行結果を保持するクラス"""
    unit: ProcessingUnit
    text: str = ""
    ttft: float = 0.0
    duration: float = 0.0
    prompt_tokens: int = 0
    candidate_tokens: int = 0
    status: str = "PENDING"  # PENDING, OK, ERROR, RETRY_FAILED
    error_message: Optional[str] = None

    @property
    def usage_str(self) -> str:
        if self.prompt_tokens > 0:
            return f" [Tokens: In={self.prompt_tokens}, Out={self.candidate_tokens}]"
        return ""
