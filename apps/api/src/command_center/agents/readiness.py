"""Bounded startup gate for agent processes, including optional local mock dependencies."""

import time
from collections.abc import Callable

import httpx
from redis import Redis
from sqlalchemy import create_engine, text

from command_center.core.config import Settings


def wait_until_ready(probe: Callable[[], None], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            probe()
            return
        except Exception:
            if time.monotonic() >= deadline:
                # Connection exceptions can contain credentials and must not reach logs.
                raise RuntimeError(
                    "Agent dependencies did not become ready within the deadline"
                ) from None
            time.sleep(min(1, max(0, deadline - time.monotonic())))


def main() -> None:
    settings = Settings()
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 3})
    redis: Redis = Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
    try:
        with httpx.Client(timeout=3, follow_redirects=False) as client:

            def probe() -> None:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                if not redis.ping():
                    raise RuntimeError("Redis is not ready")
                for url in [
                    f"{settings.internal_api_url.rstrip('/')}/health/ready",
                    *settings.agent_dependency_urls,
                ]:
                    response = client.get(url)
                    response.raise_for_status()

            wait_until_ready(probe)
    finally:
        redis.close()
        engine.dispose()


if __name__ == "__main__":
    main()
