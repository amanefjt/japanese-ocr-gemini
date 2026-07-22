import asyncio
import re
import time
from pathlib import Path
from typing import Optional
from google import genai
from google.genai import types
from aiolimiter import AsyncLimiter
from models import OCRConfig, ProcessingUnit, OCRResult
from .tier_manager import tier_manager, GeminiTier

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

    async def extract_text(self, unit: ProcessingUnit, sem: asyncio.Semaphore) -> OCRResult:
        """Gemini APIを呼び出し、テキストを取得する"""
        result = OCRResult(unit=unit)
        
        for attempt in range(5):
            try:
                with open(unit.image_path, "rb") as f:
                    image_data = f.read()
                
                async with sem:
                    async with self.limiter:
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
                            model=self.config.model_id,
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
                    # ティアマネージャーへ通知（ダウンシフト）
                    tier_manager.notify_429()
                    self._refresh_limiter()
                    
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
