"""
quick_api_test.py
One-shot diagnostic: fetch 1 event, 1 market's holders, then 1 wallet's positions.
Run with: python quick_api_test.py
"""

import asyncio
import aiohttp
import json


BASE_GAMMA = "https://gamma-api.polymarket.com"
BASE_DATA  = "https://data-api.polymarket.com"
TIMEOUT    = aiohttp.ClientTimeout(total=20)


async def fetch(session: aiohttp.ClientSession, url: str, params: dict = None):
    print(f"\n  → GET {url}")
    if params:
        print(f"     params: {params}")
    try:
        async with session.get(url, params=params) as r:
            print(f"     status: {r.status}")
            text = await r.text()
            print(f"     body (first 600 chars):\n{text[:600]}")
            return r.status, text
    except Exception as e:
        print(f"     ERROR: {e}")
        return None, None


async def main():
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:

        # ── STEP 1: search events ──────────────────────────────────────────
        print("\n" + "="*60)
        print("STEP 1 — Search events for 'iran'")
        print("="*60)
        status, body = await fetch(session, f"{BASE_GAMMA}/public-search", {"q": "iran", "limit": 3})
        if status != 200 or not body:
            print("❌ Cannot reach Gamma API. Check network/VPN.")
            return

        try:
            data = json.loads(body)
        except:
            print("❌ Response is not JSON")
            return

        # Inspect top-level keys
        print(f"\n  Top-level keys returned: {list(data.keys()) if isinstance(data, dict) else type(data)}")

        events = []
        if isinstance(data, dict):
            events = data.get('events', data.get('data', []))
        elif isinstance(data, list):
            events = data

        if not events:
            print("❌ No events found at all — API shape may have changed!")
            print(f"   Full response: {body[:1000]}")
            return

        print(f"  ✅ Got {len(events)} events")
        event = events[0]
        slug  = event.get('slug')
        print(f"  First event: '{event.get('title', '?')}' (slug={slug})")

        # ── STEP 2: get event details → markets ────────────────────────────
        print("\n" + "="*60)
        print(f"STEP 2 — Get event details: {slug}")
        print("="*60)
        status, body = await fetch(session, f"{BASE_GAMMA}/events/slug/{slug}")
        if status != 200:
            print("❌ Could not fetch event details")
            return

        event_detail = json.loads(body)
        markets = event_detail.get('markets', [])
        print(f"  Markets in event: {len(markets)}")
        if not markets:
            print("❌ No markets — check event structure")
            return

        condition_id = markets[0].get('conditionId')
        print(f"  First market conditionId: {condition_id}")
        print(f"  Market keys: {list(markets[0].keys())}")

        # ── STEP 3: get holders ────────────────────────────────────────────
        print("\n" + "="*60)
        print(f"STEP 3 — Get holders for conditionId={condition_id}")
        print("="*60)
        status, body = await fetch(session, f"{BASE_DATA}/holders", {"market": condition_id, "limit": 5})
        if status != 200:
            print("❌ Holders endpoint failed")
            return

        holders_raw = json.loads(body)
        print(f"\n  Holders response type: {type(holders_raw)}")

        # Extract wallet from whatever shape the API returned
        wallet = None
        holder_name = "?"
        if isinstance(holders_raw, list) and holders_raw:
            first = holders_raw[0]
            print(f"  First item keys: {list(first.keys()) if isinstance(first, dict) else first}")
            # Current expected shape: [{"holders": [...]}]
            inner = first.get('holders', []) if isinstance(first, dict) else []
            if inner:
                wallet = inner[0].get('proxyWallet')
                holder_name = inner[0].get('name', wallet[:8] if wallet else '?')
                print(f"  ✅ Got {len(inner)} holders. First: name={holder_name}, wallet={wallet}")
            else:
                # Maybe the API now returns flat list of holders directly
                wallet = first.get('proxyWallet') or first.get('address')
                holder_name = first.get('name', '?')
                print(f"  ℹ️ Flat holder shape? proxyWallet={wallet}")
        elif isinstance(holders_raw, dict):
            print(f"  Dict keys: {list(holders_raw.keys())}")

        if not wallet:
            print("❌ Could not extract wallet address from holders response")
            return

        # ── STEP 4: fetch active positions for that wallet ─────────────────
        print("\n" + "="*60)
        print(f"STEP 4 — Active positions for wallet={wallet[:10]}...")
        print("="*60)
        status, body = await fetch(session, f"{BASE_DATA}/positions", {"user": wallet})
        if status != 200:
            print("❌ Positions endpoint failed")
            return

        positions = json.loads(body)
        print(f"\n  Response type: {type(positions)}")
        if isinstance(positions, list) and positions:
            first_pos = positions[0]
            print(f"  Total active positions: {len(positions)}")
            print(f"  First position keys: {list(first_pos.keys())}")
            print(f"  Key fields:")
            for field in ['title', 'size', 'initialValue', 'currentValue', 'value', 'outcome', 'proxyWallet']:
                print(f"     {field}: {first_pos.get(field, '❌ NOT PRESENT')}")
        else:
            print(f"  Active positions response: {body[:400]}")

        # ── STEP 5: fetch closed positions for that wallet ─────────────────
        print("\n" + "="*60)
        print(f"STEP 5 — Closed positions for wallet={wallet[:10]}...")
        print("="*60)
        status, body = await fetch(session, f"{BASE_DATA}/closed-positions", {"user": wallet, "limit": 5})
        if status != 200:
            print("❌ Closed-positions endpoint failed")
            return

        closed = json.loads(body)
        print(f"\n  Response type: {type(closed)}")
        if isinstance(closed, list) and closed:
            first_closed = closed[0]
            print(f"  Total closed positions: {len(closed)}")
            print(f"  First position keys: {list(first_closed.keys())}")
            print(f"  Key fields:")
            for field in ['title', 'totalBought', 'avgPrice', 'realizedPnl', 'invested', 'conditionId', 'proxyWallet']:
                print(f"     {field}: {first_closed.get(field, '❌ NOT PRESENT')}")
        else:
            print(f"  Closed positions response: {body[:400]}")

        print("\n" + "="*60)
        print("✅ DIAGNOSTIC COMPLETE")
        print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
