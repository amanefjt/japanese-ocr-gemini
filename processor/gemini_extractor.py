import asyncio
import random
import re
import time
from pathlib import Path
from typing import Optional
from google import genai
from google.genai import types
from aiolimiter import AsyncLimiter
from models import OCRConfig, ProcessingUnit, OCRResult
from .tier_manager import tier_manager, GeminiTier
from .model_rotator import model_rotator

MODEL_ROTATION_RETRY_DELAY_BASE = 1.0  # モデル切替直後の待機秒数（短いジッターのみ）

class GeminiExtractor:
    """Gemini API を用いた情報抽出を担当するクラス (Extractor)"""

    def __init__(self, config: OCRConfig):
        self.config = config
        self.client = genai.Client(api_key=config.api_key)
        # 初期状態の設定（後で動的に参照するように変更を検討）
        self.limiter = AsyncLimiter(config.rpm_limit, 60)

    def _refresh_limiter(self):
        """TierManager の現在の設定に合わせて Limiter を更新する"""
        current_rpm = tier_manager.settings.rpm_limit
        if self.limiter.max_rate != current_rpm:
            self.limiter = AsyncLimiter(current_rpm, 60)

    async def extract_text(
        self,
        unit: ProcessingUnit,
        sem: asyncio.Semaphore,
        model_override: Optional[str] = None,
        limiter_override: Optional[AsyncLimiter] = None,
        model_pinned: bool = False,
    ) -> OCRResult:
        """Gemini APIを呼び出し、テキストを取得する

        model_pinned=True のとき、呼び出し元が指定した model_override を
        ModelRotator に上書きさせない（バッチ単位ラウンドロビンなど、意図的に
        特定モデルへ固定発行したい場合に使う。429時もモデルローテーションではなく
        従来のダウンシフト+待機にフォールバックする）。
        """
        result = OCRResult(unit=unit)
        active_limiter = limiter_override or self.limiter

        for attempt in range(5):
            base_model = model_override or self.config.model_id
            current_model = base_model if model_pinned else model_rotator.resolve(base_model)
            try:
                with open(unit.image_path, "rb") as f:
                    image_data = f.read()

                async with sem:
                    async with active_limiter:
                        start_time = time.time()
                        first_token_time = None
                        full_text = []

                        # プロンプトを文脈付きでフォーマット
                        formatted_prompt = unit.prompt.format(prev_context=unit.prev_context)

                        # 注: google-genai SDK (PyPI最新1.47.0時点) は thinking_level 未対応で
                        # ThinkingConfig(thinking_level=...) が pydantic ValidationError になる。
                        # SDKが対応するまでは thinking_budget で代替する。
                        # budget=0（無効化）は temperature=0.0 と組み合わせると同一フレーズを
                        # 数万文字繰り返す暴走が実測で再現したため、小さめの正の値を使う。
                        generate_config = types.GenerateContentConfig(
                            temperature=0.0,
                            thinking_config=types.ThinkingConfig(thinking_budget=512)
                        )

                        stream = await self.client.aio.models.generate_content_stream(
                            model=current_model,
                            contents=[
                                formatted_prompt,
                                types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
                            ],
                            config=generate_config
                        )
                        
                        async for chunk in stream:
                            if first_token_time is None:
                                first_token_time = time.time()
                            if chunk.text:
                                full_text.append(chunk.text)
                        
                        end_time = time.time()
                        result.ttft = (first_token_time - start_time) if first_token_time else 0.0
                        result.duration = end_time - start_time
                        
                        if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                            m = chunk.usage_metadata
                            result.prompt_tokens = m.prompt_token_count
                            result.candidate_tokens = m.candidates_token_count

                        result.text = "".join(full_text)
                        if result.text:
                            result.status = "OK"
                            return result
                        
                        result.status = "ERROR"
                        result.error_message = "Empty response"
                        return result

            except Exception as e:
                err_msg = str(e)
                if any(code in err_msg for code in ["429", "RESOURCE_EXHAUSTED"]):
                    # モデルローテーション（同一キー内で完結、client再生成不要）をダウンシフトより
                    # 優先して試みる。プールを使い切って初めて従来の待機付きダウンシフトへ。
                    # model_pinned時はラウンドロビン発行元が明示したモデルを尊重し介入しない。
                    if not model_pinned and model_rotator.is_pool_member(current_model) and model_rotator.has_next():
                        new_model = model_rotator.advance()
                        print(f"  [ModelRotator] 429検知: {new_model} へモデルローテーション")
                        await asyncio.sleep(MODEL_ROTATION_RETRY_DELAY_BASE + random.uniform(0, 1.0))
                    else:
                        # ティアマネージャーへ通知（ダウンシフト）
                        tier_manager.notify_429()
                        self._refresh_limiter()
                        if not limiter_override:
                            active_limiter = self.limiter

                        match = re.search(r'(?:retry in |after )(\d+)', err_msg)
                        wait_sec = int(match.group(1)) + 1 if match else (2 ** attempt) + 10
                        await asyncio.sleep(wait_sec)
                elif any(code in err_msg for code in ["500", "503", "504"]):
                    await asyncio.sleep(5)
                else:
                    result.status = "ERROR"
                    result.error_message = err_msg
                    return result
        
        result.status = "RETRY_FAILED"
        result.error_message = "All retries failed"
        return result
