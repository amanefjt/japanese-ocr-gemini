import enum
from dataclasses import dataclass
from typing import Dict

class GeminiTier(enum.Enum):
    PAID = "paid"
    FREE = "free"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class TierSettings:
    concurrency: int
    rpm_limit: int

# ティアごとの標準設定
TIER_PROFILES: Dict[GeminiTier, TierSettings] = {
    GeminiTier.PAID: TierSettings(concurrency=20, rpm_limit=2000),
    GeminiTier.FREE: TierSettings(concurrency=3, rpm_limit=15),
    GeminiTier.UNKNOWN: TierSettings(concurrency=20, rpm_limit=2000) # 有料版で開始
}

class TierManager:
    """APIキーのティア状態を動的に管理するシングルトン。"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.current_tier = GeminiTier.UNKNOWN
            cls._instance.is_downgraded = False
        return cls._instance

    @property
    def settings(self) -> TierSettings:
        """現在のティアに応じた設定を返す。"""
        return TIER_PROFILES[self.current_tier]

    def set_tier(self, tier: GeminiTier):
        """ティアを明示的に設定。"""
        self.current_tier = tier

    def notify_429(self):
        """429 RESOURCE_EXHAUSTED を検知した際のダウンシフト処理。"""
        if not self.is_downgraded:
            print("\n[TierManager] !!! 429 RESOURCE_EXHAUSTED detected. Downgrading to FREE tier. !!!")
            self.current_tier = GeminiTier.FREE
            self.is_downgraded = True

# グローバルなシングルトンインスタンス
tier_manager = TierManager()
