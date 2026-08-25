import asyncio
from collections import defaultdict
from datetime import datetime, timedelta


class RateLimiter:
    """Rate limiter em memória por chave. Thread-safe via asyncio.Lock."""

    def __init__(self) -> None:
        self._counts: dict[str, list[datetime]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        async with self._lock:
            now = datetime.utcnow()
            cutoff = now - timedelta(seconds=window_seconds)
            self._counts[key] = [t for t in self._counts[key] if t > cutoff]
            if len(self._counts[key]) >= max_requests:
                return False
            self._counts[key].append(now)
            return True

    async def get_wait_seconds(self, key: str, window_seconds: int) -> int:
        """Segundos até que esta chave possa fazer uma nova requisição (0 se não bloqueada)."""
        async with self._lock:
            now = datetime.utcnow()
            cutoff = now - timedelta(seconds=window_seconds)
            active = [t for t in self._counts.get(key, []) if t > cutoff]
            if not active:
                return 0
            oldest = min(active)
            secs = int((oldest + timedelta(seconds=window_seconds) - now).total_seconds()) + 1
            return max(0, secs)

    async def reset(self, key: str) -> None:
        async with self._lock:
            self._counts.pop(key, None)


# Instância global — compartilhada entre requests
rate_limiter = RateLimiter()
