---
description: Simple workflow, works
---

Polymarket OSINT Engine - Audit Workflow
Objective
Systematically verify code compliance with project standards to prevent data loss bugs, API bans, and false negative/positive classifications.

Pre-Audit Setup

Load Context:

Read .agent/rules/project-standards.md in full
Review current files: search_query.py, poly_fetcher.py, rules.py, engine.py
Check quick_api_test.py for latest API field verification


Understand Critical Risks:

🚨 Severity 1 (Project-Breaking): API bans, data loss, crashes
⚠️ Severity 2 (False Negatives): Missing real insiders
📊 Severity 3 (Code Quality): Maintainability issues




Audit Checklist
✅ Section 1: Module Architecture (Standards § 1)
Check: Separation of Concerns
python# ❌ VIOLATION EXAMPLE:
# In poly_fetcher.py
if whale_score > HeuristicsConfig.THRESHOLD:  # Business logic in fetcher!
Verification Steps:

Scan search_query.py:

 Contains ONLY query parsing and matching functions
 No imports from rules, poly_fetcher, or engine
 No I/O operations (print, file access, API calls)


Scan poly_fetcher.py:

 Contains ONLY API interaction and rate limiting
 No imports from rules or engine
 No classification logic or threshold checks


Scan rules.py:

 Contains ONLY classification logic and thresholds
 No imports from poly_fetcher or engine
 No API calls or I/O operations


Scan engine.py:

 Orchestrates other modules, doesn't reimplement their logic
 No direct session.get() calls (must use poly_fetcher)
 No inline threshold checks (must use HeuristicsConfig)



Severity: 🚨 Violations = Code smell indicating future maintenance hell

✅ Section 2: Configuration Centralization (Standards § 1.2)
Check: All numeric constants in HeuristicsConfig
Automated Scan:
python# Search for prohibited patterns across all files:

PATTERN 1: Hardcoded thresholds
  grep -n "if.*> [0-9]" *.py
  grep -n "if.*< [0-9]" *.py
  
PATTERN 2: Magic numbers in sleeps
  grep -n "asyncio.sleep([0-9]" *.py
  
PATTERN 3: Hardcoded limits
  grep -n "limit\s*=\s*[0-9]" *.py
Verification:

Check rules.py:

 HeuristicsConfig class exists
 Contains ALL thresholds used in project
 Each constant has descriptive name and comment


Check all other files:

 No inline numeric comparisons (except 0, 1, -1)
 All thresholds reference HeuristicsConfig.CONSTANT_NAME
 All delays reference class constants



Common Violations:
python# ❌ In engine.py
if position['cost'] > 5000:  # VIOLATION - hardcoded
await asyncio.sleep(2)       # VIOLATION - magic number

# ✅ CORRECT
if position['cost'] >= HeuristicsConfig.MIN_POSITION_SIZE:
await asyncio.sleep(PolymarketAPI.REQUEST_DELAY)
Severity: 🚨 Severity 1 - Makes A/B testing impossible, breaks threshold tuning

✅ Section 3: API Integration (Standards § 2)
Check 3.1: Field Name Verification
Verification Steps:

Run quick_api_test.py:

bash   python quick_api_test.py > api_audit_output.txt

Compare actual field names vs code:

 Active positions use initialValue (not spent or value)
 Closed positions use realizedPnl (not pnl)
 Holders use proxyWallet (not user or address)
 All .get() calls use verified field names


Check docstrings document field names:

python   # ✅ REQUIRED in docstrings
   """
   API Fields (verified YYYY-MM-DD):
     - realizedPnl: float (NOT 'pnl')
     - proxyWallet: str (NOT 'user')
   """
Common Violations:
python# ❌ Using wrong field name
pnl = cb.get('pnl', 0)  # Field doesn't exist! Should be 'realizedPnl'

# ❌ Direct access without .get()
wallet = holder['proxyWallet']  # Crashes if missing

# ✅ CORRECT
pnl = float(cb.get('realizedPnl', 0))
wallet = holder.get('proxyWallet')
Severity: 🚨 Severity 1 - Causes crashes or silent data loss

Check 3.2: Rate Limiting Implementation
Verification Steps:

Check poly_fetcher.py has:

 _semaphore = asyncio.Semaphore() in __init__
 REQUEST_DELAY constant (minimum 1.0)
 MAX_CONCURRENT_REQUESTS constant (maximum 5)
 _rate_limit() method enforcing delay
 ALL API calls go through async with self._semaphore:


Scan for violations:

python   # Search for direct API calls
   grep -n "session.get" *.py
   # Should ONLY appear inside poly_fetcher._fetch()

Check semaphore is entered before rate_limit:

python   # ✅ CORRECT order
   async with self._semaphore:
       await self._rate_limit()
       # ... make request
Common Violations:
python# ❌ Direct API call in engine.py
async with session.get(url):  # BANNED - bypasses rate limiter

# ❌ Rate limit without semaphore
await self._rate_limit()
async with session.get(url):  # No concurrent control!
Severity: 🚨 Severity 1 - Causes IP bans (30+ minute downtime)

Check 3.3: Retry Logic with Exponential Backoff
Verification:

Check _fetch() method has:

 for attempt in range(retries): loop
 429 handling with exponential backoff
 403 handling with clear message
 Connection error retry logic


Verify backoff formula:

python   # ✅ REQUIRED pattern
   if response.status == 429:
       wait_time = 30 * (2 ** attempt)  # 30s, 60s, 120s
       await asyncio.sleep(wait_time)
       continue
Severity: ⚠️ Severity 2 - Increases rate limit failures

✅ Section 4: Data Flow Logic (Standards § 3) - MOST CRITICAL
Check 4.1: Event → Market → Holder Hierarchy
THE GOLDEN RULE: Filter events by query, get ALL markets from matched events, filter positions by query.
Verification Steps:

In engine.py, check _process_event():

python   # ✅ CORRECT pattern
   async def _process_event(self, api, slug):
       event_details = await api.get_event_details(slug)
       markets = event_details.get('markets', [])
       
       # CRITICAL: Process ALL markets, don't filter here
       for market in markets:
           condition_id = market.get('conditionId')
           holders = await api.get_market_holders(condition_id)
           # Register ALL holders

CRITICAL CHECK: Search for prohibited market filtering:

python   # ❌ VIOLATION - causes data loss
   for market in markets:
       if self.matcher.matches(market['question']):  # WRONG!
           holders = get_holders(market)

In _process_whale_positions():

python   # ✅ CORRECT - filter positions here
   for position in all_positions:
       if self.matcher.matches(position['title']):
           topic_positions.append(position)
```

**Why This Matters:**
```
Event: "Israel strikes Iran by...?"
├─ Market 1: "By Feb 28?" (no "israel" keyword)
├─ Market 2: "By Mar 31?" (no "israel" keyword)
└─ Market 3: "By Jun 30?" (no "israel" keyword)

If you filter markets → 0 holders found
If you get ALL markets → find anoin123 with $2M positions ✅
Test Case:
python# Create test to verify this logic
query = "israel"
event_title = "Israel strikes Iran by...?"
market_questions = ["By Feb 28?", "By Mar 31?"]

# Event matches query ✅
assert matcher.matches(event_title)

# Markets DON'T match query individually
assert not any(matcher.matches(q) for q in market_questions)

# But we should STILL get holders from those markets
# This is the critical insight!
Severity: 🚨 Severity 1 - Causes complete data loss (anoin123 bug)

✅ Section 5: Classification Logic (Standards § 4)
Check 5.1: Entry Gate vs Qualification Logic
Verification:

Check rules.py - EntryGate.evaluate():

 Uses OR logic between smoking_gun and heavy_hitter
 Returns early on first match (efficient)



python   # ✅ CORRECT
   if smoking_gun_closed or smoking_gun_active:
       return {'passed': True, ...}
   
   if heavy_hitter_condition:
       return {'passed': True, ...}

Check QualificationFilters.passes():

 Uses AND logic (all checks must pass)
 Returns False on first failure (efficient)



Common Violations:
python# ❌ Entry gate with AND - too restrictive
if smoking_gun AND heavy_hitter:
    pass_entry()

# ❌ Qualification with OR - too loose
if metric1 >= MIN OR metric2 >= MIN:
    pass_qualification()
Severity: ⚠️ Severity 2 - Causes false negatives

Check 5.2: Pure Active Whale Handling
CRITICAL BUG FIX CHECK:
Verification:

In QualificationFilters.passes():

python   # ✅ REQUIRED pattern
   
   # Always-required structural checks (no closed positions needed)
   structural_checks = [
       topic_positions >= MIN,
       total_exposure >= MIN,
       concentration >= MIN
   ]
   
   # Performance checks ONLY when closed history exists
   if metrics['historical_total'] > 0:
       perf_checks = [
           historical_total >= MIN,
           profit_factor >= MIN,
           roi >= MIN
       ]

CRITICAL: Verify performance checks are SKIPPED for pure active whales:

python   # Test case
   whale_with_only_active = {
       'active_topic_positions': [{'spent': 10000, ...}],
       'closed_topic_positions': [],  # No closed positions
       'historical_total': 0
   }
   
   # Should pass structural checks, skip performance checks
   # Previously would fail with profit_factor=0, roi=0
Why This Matters:

Pure active whale with $10k position on Iran
No closed positions yet (new to platform or holding long-term)
Old code: Failed with PF=0, ROI=0 → False negative
New code: Skips performance checks → Correctly identified

Severity: 🚨 Severity 1 - Causes false negatives on valuable targets

✅ Section 6: Error Handling & Debugging (Standards § 5)
Check 6.1: Debug Mode Implementation
Verification:

Check engine.py has:

 def __init__(self, query_string, debug: bool = True)
 self.debug = debug stored
 Debug prints controlled by if self.debug:


Check debug output includes:

 Event/market/holder counts
 Topic position counts per whale
 Entry gate pass/fail with reasons
 Qualification pass/fail with reasons



Severity: 📊 Severity 3 - Makes debugging 10x harder

Check 6.2: Error Context in Exceptions
Verification:

Search for bare exception handlers:

python   # ❌ VIOLATION
   except Exception as e:
       print(f"Error: {e}")  # No context!
   
   # ✅ CORRECT
   except Exception as e:
       print(f"❌ Error processing whale {wallet[:8]}")
       print(f"   Event: {event_title}")
       print(f"   Error: {e}")
Severity: 📊 Severity 3 - Slows down debugging

✅ Section 7: Testing Compliance (Standards § 6)
Check 7.1: Pre-Deployment Checklist
Verification:

Check for test mode in code:

python   # ✅ Should exist in _fetch_all_positions()
   if len(self.registry) > 100:
       print(f"⚠️ WARNING: {len(self.registry)} whales")
       max_whales = input("How many to analyze? (default=50): ")

Check for field name verification:

python   # ✅ Should exist in _process_whale_positions()
   if self.debug and active_raw:
       print(f"Active fields: {list(active_raw[0].keys())}")
Severity: ⚠️ Severity 2 - Risks wasting hours on rate limits

✅ Section 8: Prohibited Patterns Scan (Standards § 8)
Automated Scan:
bash# Run these checks and flag ALL violations

# 1. Hardcoded thresholds
grep -rn "if.*[<>]=\? [0-9]\{4,\}" --include="*.py" .
# Flag: Any comparison with 4+ digit number outside HeuristicsConfig

# 2. Direct API calls
grep -rn "session\.get\|aiohttp\.get" --include="*.py" .
# Flag: Any outside poly_fetcher._fetch()

# 3. Market filtering by query
grep -rn "matcher\.matches.*market.*question" --include="*.py" .
# Flag: Market-level query filtering (data loss bug)

# 4. Direct dictionary access of API data
grep -rn "\['\(pnl\|user\|wallet\|proxyWallet\)'\]" --include="*.py" .
# Flag: Should use .get() for API fields

# 5. Magic sleep numbers
grep -rn "asyncio\.sleep\([0-9]" --include="*.py" .
# Flag: Should use class constants

# 6. Large batch processing without limiting
grep -rn "registry\.items\(\)" --include="*.py" .
# Check: Should have whale count limiting logic nearby
Severity: 🚨 Severity 1 - Each violation risks project failure

Audit Output Format
Create artifact: AUDIT_RESULTS.md
markdown# Polymarket OSINT Engine - Audit Report
**Date:** YYYY-MM-DD
**Audited By:** [Agent Name]
**Commit/Version:** [if applicable]

---

## Executive Summary
- 🚨 **Critical Issues:** X found
- ⚠️ **Warnings:** Y found
- 📊 **Code Quality:** Z found
- ✅ **Compliant Sections:** A, B, C

**Recommendation:** [PASS / CONDITIONAL PASS / FAIL]

---

## 🚨 Severity 1: Critical Issues (Project-Breaking)

##