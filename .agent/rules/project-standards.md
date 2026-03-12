---
trigger: always_on
---

Polymarket OSINT Engine - Project Standards & Best Practices
🎯 Core Mission
Detect insider trading patterns on Polymarket by analyzing whale positions with statistical rigor. Every standard exists to prevent false negatives (missing real insiders) and false positives (flagging lucky gamblers).

1. Module Architecture (NON-NEGOTIABLE)
1.1 Separation of Concerns
RULE: Each module has ONE responsibility. Never mix concerns.
pythonsearch_query.py    → Query parsing & text matching ONLY
poly_fetcher.py    → API requests & rate limiting ONLY
rules.py           → Classification logic & thresholds ONLY
engine.py          → Workflow orchestration ONLY

1.2 Configuration Centralization
RULE: ALL numeric thresholds, delays, and limits MUST be in HeuristicsConfig class in rules.py.
✅ CORRECT:
python# In rules.py
class HeuristicsConfig:
    SMOKING_GUN_SIZE = 1000
    REQUEST_DELAY = 1.5
    MAX_CONCURRENT_REQUESTS = 3

# In other files
if cost >= HeuristicsConfig.SMOKING_GUN_SIZE:
❌ PROHIBITED:
pythonif cost > 1000:  # WHERE DID 1000 COME FROM?
await asyncio.sleep(1.5)  # MAGIC NUMBER
Enforcement: Code review must reject any hardcoded numbers outside HeuristicsConfig.

2. API Integration Standards (LEARNED THE HARD WAY)
2.1 Field Name Verification
CRITICAL RULE: NEVER assume API field names. Always verify from actual responses first.
Pre-Integration Checklist:

✅ Run quick_api_test.py to see actual API response structure
✅ Print list(sample.keys()) for first record
✅ Document verified field names in docstring
✅ Use .get() with defaults, never direct access

✅ CORRECT:
python# After verifying API returns 'realizedPnl', not 'pnl'
pnl = float(cb.get('realizedPnl', 0))  # VERIFIED field name
wallet = holder.get('proxyWallet')     # VERIFIED field name

# Docstring documents verification
"""
API Response Fields (verified 2025-02-17):
  - realizedPnl: float (NOT 'pnl')
  - proxyWallet: str (NOT 'user' or 'address')
"""
❌ PROHIBITED:
pythonpnl = data['pnl']              # Crashes if field missing
wallet = holder.get('user')    # Wrong field name
Enforcement: Any KeyError on API data is a CRITICAL BUG. Patch immediately, document field name.
2.2 Rate Limiting (ABSOLUTE REQUIREMENT)
RULE: Every API request MUST go through _semaphore and _rate_limit(). No exceptions.
✅ CORRECT (see poly_fetcher.py):
pythonclass PolymarketAPI:
    REQUEST_DELAY = 1.5              # Minimum 1.0 second
    MAX_CONCURRENT_REQUESTS = 3      # Maximum 5
    
    def __init__(self):
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_REQUESTS)
    
    async def _rate_limit(self):
        # Enforce minimum delay between requests
        
    async def _fetch(self, url, params, retries=3):
        async with self._semaphore:  # REQUIRED
            await self._rate_limit()  # REQUIRED
            # ... make request
❌ PROHIBITED:
python# Direct API call bypassing rate limiter
async with session.get(url):  # BANNED - will cause IP ban
Enforcement: Any direct session.get() outside _fetch() is REJECTED. No exceptions.
2.3 Retry Logic with Exponential Backoff
RULE: All API calls must retry 429 errors with exponential backoff.
✅ REQUIRED PATTERN:
pythonasync def _fetch(self, url, params, retries=3):
    for attempt in range(retries):
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                
                elif response.status == 429:
                    wait_time = 30 * (2 ** attempt)  # 30s, 60s, 120s
                    print(f"⚠️ Rate limited - sleeping {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                    
                elif response.status == 403:
                    print(f"🚫 BANNED (403) - Wait 30+ minutes")
                    return None
```

**Enforcement:** Any API call without retry logic is INCOMPLETE.

---

## 3. Data Flow Logic (THE CRITICAL INSIGHT)

### 3.1 Event → Market → Holder Hierarchy
**MOST IMPORTANT RULE IN THE PROJECT:**
```
EVENT (filter by query match)
  ↓
  ├─ MARKET 1 (get ALL - don't filter)
  ├─ MARKET 2 (get ALL - don't filter)
  └─ MARKET 3 (get ALL - don't filter)
       ↓
       ├─ HOLDER 1
       ├─ HOLDER 2
       └─ HOLDER 3
            ↓
            ├─ POSITION 1 (filter by query here)
            ├─ POSITION 2 (filter by query here)
            └─ POSITION 3 (filter by query here)
```

**Why This Matters:**
```
Event: "Israel strikes Iran by...?"
├─ Market 1: "By February 28?" (no "israel" in question)
├─ Market 2: "By March 31?"    (no "israel" in question)
└─ Market 3: "By June 30?"     (no "israel" in question)
If you filter markets by query match, you get ZERO holders. This is why anoin123 wasn't found.
✅ CORRECT PATTERN:
python# In engine.py - _process_event()
async def _process_event(self, api, slug):
    event_details = await api.get_event_details(slug)
    event_title = event_details.get('title', '')
    
    # Event already matched in _search_events(), so process ALL markets
    markets = event_details.get('markets', [])
    
    for market in markets:
        condition_id = market.get('conditionId')
        
        # ✅ Get holders from EVERY market - no filtering
        holders = await api.get_market_holders(condition_id)
        
        for holder in holders:
            self.registry[wallet] = {...}

# LATER, in _process_whale_positions()
for position in all_positions:
    if self.matcher.matches(position['title']):  # ✅ Filter HERE
        topic_positions.append(position)
❌ PROHIBITED:
pythonfor market in markets:
    # ❌ WRONG - too restrictive, misses all holders
    if self.matcher.matches(market['question']):
        holders = await api.get_market_holders(market['conditionId'])
Enforcement: Any market filtering by query is REJECTED. Filter at position level only.

4. Classification Logic Standards
4.1 Two-Stage Filtering Philosophy
RULE: Entry gate uses OR logic (flexible). Qualification uses AND logic (strict).
python# ✅ CORRECT: OR at entry, AND at qualification

# Stage 1: Entry Gate (loose - cast wide net)
if smoking_gun OR heavy_hitter:
    proceed_to_analysis()

# Stage 2: Qualification (strict - all must pass)
if (topic_positions >= MIN AND 
    exposure >= MIN AND 
    profit_factor >= MIN):
    proceed_to_classification()
Why: Entry gate catches different insider patterns. Qualification ensures minimum quality.
❌ PROHIBITED:
python# Entry gate with AND logic - misses single-bet insiders
if smoking_gun AND heavy_hitter:
4.2 Pure Active Whale Handling
CRITICAL BUG FIX (see rules.py QualificationFilters):
RULE: Whales with ONLY active positions (no closed history) skip performance filters.
✅ CORRECT:
python# From rules.py - QualificationFilters.passes()
if metrics['historical_total'] > 0:
    # Has closed positions - enforce performance checks
    if profit_factor < MIN_PROFIT_FACTOR:
        return False, "Low profit factor"
else:
    # Pure active whale - skip performance checks
    # (Can't calculate profit_factor without closed positions)
    pass
Why: Pure active whales with $10k positions would fail with profit_factor=0, roi=0. This was causing false negatives.

5. Error Handling & Debugging
5.1 Debug Mode (Required)
RULE: All major operations must have debug logging controlled by debug flag.
✅ REQUIRED PATTERN:
pythonclass PolymarketOSINTEngine:
    def __init__(self, query_string: str, debug: bool = True):
        self.debug = debug
    
    def _process_whale_positions(self, info: Dict):
        if self.debug:
            print(f"🔬 Processing: {info['name']}")
            print(f"   Raw: {len(info['active_raw'])} active, {len(info['closed_raw'])} closed")
            print(f"   Topic: {len(topic_positions)} positions matched query")
5.2 Error Context
RULE: Errors must include context about what was being processed.
✅ CORRECT:
pythonexcept Exception as e:
    print(f"❌ Error processing whale {wallet[:8]}")
    print(f"   Event: {event_title}")
    print(f"   Market: {condition_id}")
    print(f"   Error: {e}")
❌ PROHIBITED:
pythonexcept Exception as e:
    print(f"Error: {e}")  # WHERE? WHAT DATA?

6. Testing Requirements
6.1 Pre-Deployment Checklist
MANDATORY before running on 100+ whales:
python# 1. Test API connectivity
python quick_api_test.py  # Verify all endpoints work

# 2. Test with 5 whales only
registry_items = list(self.registry.items())[:5]

# 3. Verify field names
if self.debug and active_raw:
    print(f"Active fields: {list(active_raw[0].keys())}")
    print(f"Closed fields: {list(closed_raw[0].keys())}")

# 4. Check rate limiting
# Run for 2 minutes, should see NO 429 errors

# 5. Verify topic matching
print(f"Sample topic position: {topic_positions[0]['raw']['title']}")
Enforcement: NEVER run on 500+ whales without completing this checklist.
6.2 Threshold Validation
RULE: When no whales pass filters, lower thresholds temporarily to verify data flow.
python# For debugging - temporarily lower ALL thresholds
SMOKING_GUN_SIZE = 500          # From 5000
HEAVY_HITTER_EXPOSURE = 2000    # From 15000
MIN_ONTOPIC_POSITIONS = 2       # From 5
If whales STILL don't pass → data extraction bug, not threshold issue.

7. Code Style Conventions
7.1 Naming
python# ✅ GOOD
whale_data: Dict           # Descriptive
topic_positions: List      # Clear purpose
entry_result: Dict         # What it contains

# ❌ BAD
data: Dict                 # Too generic
temp: List                 # Unclear
result: Dict               # What kind?
7.2 Docstrings (Required)
pythonasync def fetch_whale_positions(self, wallet: str, display_name: str) -> Dict:
    """
    Fetch complete position data for one whale
    
    Args:
        wallet: Wallet address (from 'proxyWallet' field)
        display_name: Human-readable name
        
    Returns:
        Dict with 'active' and 'closed' position lists
        
    Rate Limit:
        2s delay enforced between calls
        
    API Fields Verified:
        2025-02-17 - Returns list of position dicts
    """

8. Prohibited Patterns (NEVER DO THIS)
❌ Critical Violations
python# 1. Hardcoded thresholds
if position['cost'] > 5000:  # REJECTED

# 2. Direct API calls
async with session.get(url):  # BANNED - causes IP ban

# 3. Filtering markets by query
if self.matcher.matches(market['question']):  # REJECTED - too restrictive

# 4. Assuming field names
pnl = data['pnl']  # REJECTED - use .get() and verify field

# 5. Magic numbers
await asyncio.sleep(2)  # REJECTED - use HeuristicsConfig constant

# 6. Untested large batches
# Processing 500 whales without 5-whale test first - REJECTED
```

---

## 9. Enforcement Mode

**Mode:** Always On - Standards Override User Requests

### When Agent Detects Violation:
```
🚫 STANDARDS VIOLATION DETECTED

Requested change:
  Add inline threshold `if cost > 5000`

Violates:
  Section 1.2 - Configuration Centralization
  ALL thresholds must be in HeuristicsConfig

Compliant alternative:
  1. Add to rules.py: THRESHOLD_NAME = 5000
  2. Use: if cost >= HeuristicsConfig.THRESHOLD_NAME

Actions:
  [1] Implement compliant version
  [2] Request standards exception (requires justification)
  [3] Explain why this standard exists
  
Choose: _
```

**No Exceptions For:**
- Rate limiting bypass (causes IP ban)
- Market filtering by query (causes data loss)
- Assuming API field names (causes crashes)

---

## 10. Quick Reference Card
```
╔═══════════════════════════════════════════════════════════╗
║           GOLDEN RULES - MEMORIZE THESE                   ║
╠═══════════════════════════════════════════════════════════╣
║ 1. Filter EVENTS by query, not markets                   ║
║ 2. Verify API field names with quick_api_test.py first   ║
║ 3. All thresholds in HeuristicsConfig (rules.py)         ║
║ 4. Rate limit EVERYTHING through _semaphore              ║
║ 5. Test with 5 whales