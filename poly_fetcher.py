"""
poly_fetcher.py
Async data fetching from Polymarket APIs with rate limiting
"""

import aiohttp
import asyncio
from typing import Optional, Dict, List


class PolymarketAPI:
    """Handles all Polymarket API interactions with rate limiting"""
    
    BASE_GAMMA = "https://gamma-api.polymarket.com"
    BASE_DATA = "https://data-api.polymarket.com"
    TIMEOUT = 20  # seconds
    
    # Rate limiting configuration
    REQUEST_DELAY = 1.5   # seconds between requests (was 2.0)
    MAX_CONCURRENT_REQUESTS = 3  # (was 2 — caused deadlock with gather())
    MAX_RETRIES = 3
    RETRY_DELAY = 10  # seconds after rate limit
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_REQUESTS)
        self._last_request_time = 0
    
    async def __aenter__(self):
        """Async context manager entry"""
        # FIX: Use aiohttp.ClientTimeout object, not a plain int
        timeout = aiohttp.ClientTimeout(total=self.TIMEOUT)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    async def _rate_limit(self):
        """Enforce rate limiting between requests"""
        current_time = asyncio.get_event_loop().time()
        time_since_last = current_time - self._last_request_time
        
        if time_since_last < self.REQUEST_DELAY:
            await asyncio.sleep(self.REQUEST_DELAY - time_since_last)
        
        self._last_request_time = asyncio.get_event_loop().time()
    
    async def _fetch(self, url: str, params: Optional[Dict] = None, retries: int = 3) -> Optional[Dict]:
        """Fetch with retry logic and proper timeout handling"""
        
        async with self._semaphore:
            await self._rate_limit()
            
            for attempt in range(retries):
                try:
                    async with self.session.get(url, params=params) as response:
                        if response.status == 200:
                            return await response.json()
                        
                        elif response.status == 429:
                            # Rate limited - exponential backoff
                            wait_time = 30 * (2 ** attempt)  # 30s, 60s, 120s
                            print(f"⚠️  Rate limited (429) - sleeping {wait_time}s... (attempt {attempt+1}/{retries})")
                            await asyncio.sleep(wait_time)
                            continue
                        
                        elif response.status == 403:
                            print(f"🚫 BANNED (403) - IP blocked by Polymarket")
                            print(f"   Wait 10-30 minutes before trying again")
                            return None
                        
                        else:
                            print(f"⚠️  API error {response.status}: {url}")
                            return None
                
                except aiohttp.ServerTimeoutError:
                    print(f"⏱️  Timeout on attempt {attempt+1}/{retries}: {url}")
                    if attempt < retries - 1:
                        await asyncio.sleep(5)
                        continue
                    return None
                
                except aiohttp.ClientConnectorError as e:
                    wait_time = 5 * (attempt + 1)
                    print(f"🔌 Connection error (attempt {attempt+1}/{retries})")
                    if attempt < retries - 1:
                        print(f"   Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    return None
                
                except Exception as e:
                    print(f"❌ Error: {type(e).__name__}: {e}")
                    return None
            
            return None

    # --- Event Search ---
    
    async def search_events(self, query: str, limit: int = 20) -> List[Dict]:
        """
        Search for events matching query
        
        Args:
            query: Search string (use single term for best results)
            limit: Max results
            
        Returns:
            List of event objects (NOT the full response)
        """
        url = f"{self.BASE_GAMMA}/public-search"
        params = {"q": query, "limit": limit}
        
        data = await self._fetch(url, params)
        
        if data and isinstance(data, dict) and 'events' in data:
            return data['events']
        
        # --- RUNTIME DIAGNOSTIC ---
        print(f"   🔬 DIAGNOSTIC: search_events raw response type={type(data)}, value={str(data)[:200]}")
        return []
    
    async def get_event_details(self, slug: str) -> Optional[Dict]:
        """
        Get full event details by slug
        
        Args:
            slug: Event slug identifier
            
        Returns:
            Event details or None
        """
        url = f"{self.BASE_GAMMA}/events/slug/{slug}"
        return await self._fetch(url)
    
    # --- Position Data ---
    
    async def get_market_holders(self, condition_id: str, limit: int = 20) -> List[Dict]:
        """
        Get holders for a specific market
        
        Args:
            condition_id: Market condition ID
            limit: Max holders
            
        Returns:
            List of holder objects with proxyWallet and name fields
        """
        url = f"{self.BASE_DATA}/holders"
        params = {"market": condition_id, "limit": limit}
        
        data = await self._fetch(url, params)
        
        # API response: [{"holders": [{"proxyWallet": "...", "name": "..."}, ...]}]
        if data and isinstance(data, list) and len(data) > 0:
            return data[0].get("holders", [])
        
        # --- RUNTIME DIAGNOSTIC ---
        if data is not None:
            print(f"   🔬 DIAGNOSTIC holders: type={type(data)}, preview={str(data)[:200]}")
        return []
    
    async def get_active_positions(self, wallet: str) -> List[Dict]:
        """
        Get all active positions for a wallet
        
        Args:
            wallet: Wallet address
            
        Returns:
            List of active position objects
        """
        if not wallet:
            print("⚠️  Empty wallet address provided to get_active_positions")
            return []
        
        url = f"{self.BASE_DATA}/positions"
        params = {"user": wallet}
        
        data = await self._fetch(url, params)
        
        if data and isinstance(data, list):
            return data
        
        # --- RUNTIME DIAGNOSTIC (first call only) ---
        if data is not None:
            print(f"   🔬 DIAGNOSTIC active positions: type={type(data)}, preview={str(data)[:200]}")
        return []
    
    async def get_closed_positions(self, wallet: str, limit: int = 100) -> List[Dict]:
        """
        Get closed positions for a wallet
        
        Args:
            wallet: Wallet address
            limit: Max positions (lowered from 300 to reduce rate limit risk)
            
        Returns:
            List of closed position objects
        """
        if not wallet:
            print("⚠️  Empty wallet address provided to get_closed_positions")
            return []
        
        url = f"{self.BASE_DATA}/closed-positions"
        params = {"user": wallet, "limit": limit}
        
        data = await self._fetch(url, params)
        
        if data and isinstance(data, list):
            return data
        
        # --- RUNTIME DIAGNOSTIC ---
        if data is not None:
            print(f"   🔬 DIAGNOSTIC closed positions: type={type(data)}, preview={str(data)[:200]}")
        return []
    
    async def fetch_whale_positions(self, wallet: str, display_name: str) -> Dict:
        """
        Fetch complete position data for one whale.
        
        FIX: Previously called asyncio.gather() inside the semaphore, which
        caused a deadlock when MAX_CONCURRENT_REQUESTS=2 (both slots consumed
        by the outer gather, inner gather then blocked forever).
        Now fetches active and closed sequentially to avoid deadlock.
        
        Args:
            wallet: Wallet address
            display_name: Human-readable name
            
        Returns:
            Dict with 'active' and 'closed' position lists
        """
        if not wallet:
            print(f"  ⚠️  Skipping {display_name}: Empty wallet address")
            return {
                'wallet': wallet,
                'name': display_name,
                'active': [],
                'closed': []
            }
        
        print(f"  📡 Fetching: {display_name} ({wallet[:8]}...)")
        
        # FIX: Sequential fetch to avoid semaphore deadlock.
        # Each call acquires the semaphore independently.
        active = await self.get_active_positions(wallet)
        closed = await self.get_closed_positions(wallet)
        
        return {
            'wallet': wallet,
            'name': display_name,
            'active': active if active else [],
            'closed': closed if closed else []
        }