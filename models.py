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
    
    @classmethod
    def from_args(cls, args, api_key: str):
        if args.free:
            return cls(
                api_key=api_key,
                is_free_tier=True,
                concurrency=3,
                rpm_limit=15,
                start_page=args.start,
                end_page=args.end
            )
        return cls(
            api_key=api_key,
            start_page=args.start,
            end_page=args.end
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
