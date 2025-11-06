import asyncio
import aiohttp
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from connectors.hyperliquid_connector import HyperliquidConnector  # noqa: E402

async def check_role(wallet: str):
    connector = HyperliquidConnector()
    url = f"{connector._get_base_url(False)}/info"
    payload = {"type": "userRole", "user": wallet}
    headers = {"Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            try:
                body = await resp.json()
            except Exception:
                body = await resp.text()
            print(f"wallet: {wallet}")
            print(f"status: {resp.status}")
            print(f"body: {body}\n")

async def main():
    wallets = [
        "0xC43Abb82cAc9A5AD0dd1be8a0f1a4a4E725FCB29",
        "0xf3e8b248703528bf5200801a95c1e308b3deafca",
        "0x58c1df24f95048bf69e1459348b3895deec81830",
    ]
    for w in wallets:
        await check_role(w)

if __name__ == "__main__":
    asyncio.run(main())
