"""Verify configured research services, optionally using a public example query and URL."""

import argparse
import asyncio

import httpx
from command_center.core.config import Settings
from command_center.integrations.clients import (
    ConnectionState,
    FirecrawlClient,
    SearxngClient,
)


async def check(functional: bool) -> None:
    settings = Settings()
    async with httpx.AsyncClient(
        timeout=5, trust_env=False, follow_redirects=False
    ) as http:
        firecrawl = FirecrawlClient(
            http, settings.firecrawl_url, settings.firecrawl_api_key.get_secret_value()
        )
        searxng = SearxngClient(http, settings.searxng_url)
        statuses = await asyncio.gather(firecrawl.status(), searxng.status())
        for status in statuses:
            print(f"{status.name}: {status.state.value}")
        if any(status.state != ConnectionState.ONLINE for status in statuses):
            raise SystemExit(1)
        if functional:
            results, page = await asyncio.gather(
                searxng.search("example.com", limit=3),
                firecrawl.scrape("https://example.com"),
            )
            if not results or not page.get("markdown"):
                raise SystemExit(
                    "Functional check returned no search results or markdown"
                )
            print(
                f"SearXNG JSON search: {len(results)} results; Firecrawl v2 scrape: markdown received"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--functional", action="store_true")
    args = parser.parse_args()
    asyncio.run(check(args.functional))
