from typing import List, Optional

# gemini-3.1-flash-lite と gemini-3.5-flash-lite は Rate Limit (RPM/RPD/TPM) が
# 無料枠・有料枠(Tier 2)とも完全一致するが、使用量カウンタは独立している
# (docs/gemini_models.md §4 実測)。この2モデルを使い分けることで無料枠の実質容量を
# 拡張できる。p2workflowy の ModelRotator (core/llm_client.py) と同じ設計思想。
DEFAULT_MODEL_FREE_POOL: List[str] = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]


class ModelRotator:
    """無料枠Liteプール内でのフォワードオンリー・モデルローテーション。

    429/503でRPD/RPMが枯渇した際、同一キー内でもう一方のLiteモデルへ切り替えることで
    処理を継続させる。プールを使い切ったら(has_next()がFalseになったら)従来どおり
    TierManagerのダウンシフト+待機にフォールバックする。
    """

    def __init__(self, pool: Optional[List[str]] = None):
        self._pool = pool or DEFAULT_MODEL_FREE_POOL
        self._index = 0

    def reset(self):
        self._index = 0

    def is_pool_member(self, model: Optional[str]) -> bool:
        return model in self._pool

    def current(self) -> str:
        return self._pool[self._index]

    def has_next(self) -> bool:
        return self._index < len(self._pool) - 1

    def advance(self) -> str:
        if self.has_next():
            self._index += 1
        return self.current()

    def resolve(self, model: Optional[str]) -> Optional[str]:
        """model がプールのメンバーなら現在のローテーション先へ差し替える。プール外はそのまま返す。"""
        if model in self._pool:
            return self.current()
        return model

    @property
    def pool(self) -> List[str]:
        return self._pool


# グローバルなシングルトンインスタンス (gocr CLIは1プロセス1回の実行なのでTierManagerと同様
# プロセスグローバルな単純状態で十分。p2workflowyのWebアプリのようなスレッド並行はない)
model_rotator = ModelRotator()
