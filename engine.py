"""
engine.py
Main orchestration - runs the complete OSINT mission
"""

import asyncio
import random
import pandas as pd
from datetime import datetime
from typing import Dict, List
from search_query import QueryParser, QueryMatcher
from poly_fetcher import PolymarketAPI
from rules import (
    HeuristicsConfig, EntryGate, MetricsCalculator, 
    WinRateAnalyzer, QualificationFilters, WhaleClassifier
)


class PolymarketOSINTEngine:
       
    def __init__(self, query_string: str, use_regex: bool = False, debug: bool = True):  # [OK] Add use_regex flag
        """
        Initialize the engine
        
        Args:
            query_string: User's search query
            use_regex: Enable regex-based matching
            debug: Enable verbose logging
        """
        self.query_root = QueryParser.parse(query_string)
        self.matcher = QueryMatcher(self.query_root, query_string, use_regex=use_regex)
        self.registry: Dict[str, Dict] = {}
        self.known_event_slugs: set = set()  # Slugs of events matched in Step 1 (used for position matching)
        self.debug = debug
        
        print(f"[QUERY] {self.matcher.get_display_query()}")
    
    async def run_mission(self):
        """Execute the complete OSINT mission with timeout"""
        print("\n" + "="*60)
        print("MISSION: POLYMARKET OSINT MISSION - INSIDER WHALE DETECTION")
        print("="*60 + "\n")
        
        try:
            # [OK] Add overall timeout (10 minutes max)
            await asyncio.wait_for(self._run_mission_internal(), timeout=3600)  # BUG FIX: was 600s (10min)   far too short for large runs
        except asyncio.TimeoutError:
            print("\n[TIMEOUT] MISSION TIMEOUT (10 minutes exceeded)")
            print("   Partial results may be available")
            self._export_partial_results()
        except KeyboardInterrupt:
            print("\n\n[STOP] MISSION INTERRUPTED BY USER")
            print("   Attempting to save partial results...")
            self._export_partial_results()
        except Exception as e:
            print(f"\n[ERROR] MISSION FAILED: {e}")
            raise

    async def _run_mission_internal(self):
        """Internal mission execution (original run_mission logic)"""
        async with PolymarketAPI() as api:
            # Step 1: Search for events
            print("[1] Searching for events...")
            events = await self._search_events(api)
            
            if not events:
                print("[ERROR] No events found matching query")
                return
            
            print(f"[OK] Found {len(events)} matching events\n")
            
            # Step 2: Extract markets and holders
            print("[2] Collecting market holders...")
            await self._collect_holders(api, events)
            
            if not self.registry:
                print("[ERROR] No holders found")
                return
            
            print(f"[OK] Found {len(self.registry)} unique whales\n")
            
            # Step 3: Fetch all positions
            print("[3] Fetching whale positions...")
            await self._fetch_all_positions(api)
            print()
            
            # Step 4: Analyze and classify
            print("[4] Analyzing and classifying whales...")
            results = self._analyze_whales()
            
            # Step 5: Export to Excel
            print("\n[5] Exporting results...")
            self._export_to_excel(results)
            
            print("\n" + "="*60)
            print("[DONE] MISSION COMPLETE")
            print("="*60)

    def _export_partial_results(self):
        """Export whatever data we have so far"""
        print("[INFO] Attempting to export partial results...")
        try:
            results = self._analyze_whales()
            self._export_to_excel(results)
        except Exception as e:
            print(f"[ERROR] Could not export partial results: {e}")
    
    async def _search_events(self, api: PolymarketAPI) -> List[Dict]:
        """Search for events matching query"""
        
        # Strategy: Search API with first available term (wider results)
        # Then filter client-side with full Boolean match logic (precision)
        
        # We need a first term to search Polymarket API
        def _get_first_term(node):
            if hasattr(node, 'term'): return node.term
            if hasattr(node, 'left'): return _get_first_term(node.left)
            return "polymarket" # fallback
            
        search_term = _get_first_term(self.query_root)
        
        print(f"   [SEARCH] Searching Polymarket API: '{search_term}' (Limit: {HeuristicsConfig.SEARCH_LIMIT})")
        all_events = await api.search_events(search_term, limit=HeuristicsConfig.SEARCH_LIMIT)
        
        if not all_events:
            print(f"   [WARN] No events found for '{search_term}'")
            return []
        
        print(f"   [DATA] API returned: {len(all_events)} events")
        
        # Filter by full query logic
        matching_events = []
        for event in all_events:
            title = event.get('title', '')
            slug  = event.get('slug', '')
            if self.matcher.matches(title):
                matching_events.append(event)
                if slug:
                    self.known_event_slugs.add(slug)  # [OK] Track matched event slugs for position matching
                print(f"      [MATCH] Match: {title}")
            else:
                print(f"      [SKIP] Skip: {title}")
        
        print(f"   [DONE] After filtering: {len(matching_events)} matching events")
        print(f"   [INFO] Known event slugs: {len(self.known_event_slugs)}")
        
        return matching_events
    
    async def _collect_holders(self, api: PolymarketAPI, events: List[Dict]):
        """
        Collect all unique holders from matched events
        
        Strategy:
        1. Events are already filtered by query in _search_events()
        2. For each matched event, get holders from ALL its markets
        3. Position filtering happens later in _process_whale_positions()
        """
        print(f"   [INFO] Collecting holders from {len(events)} matched events...")
        
        tasks = []
        for event in events:
            slug = event.get('slug')
            if slug:
                tasks.append(self._process_event(api, slug))
        
        await asyncio.gather(*tasks)
        
        print(f"\n   [STATS] Total unique whales in registry: {len(self.registry)}")

    async def _process_event(self, api: PolymarketAPI, slug: str):
        """
        Process a single event and collect holders from ALL its markets
        
        Logic: If EVENT matches query   Get holders from ALL markets in that event
        """
        event_details = await api.get_event_details(slug)
        
        if not event_details:
            print(f"      [WARN]  Could not fetch details for slug: {slug}")
            return
        
        event_title = event_details.get('title', 'Unknown')
        markets = event_details.get('markets', [])
        
        # [OK] Event already matched in _search_events(), 
        # so get holders from ALL markets in this event
        
        if not markets:
            print(f"      [WARN]  No markets in event: {event_title}")
            return
        
        print(f"   [LIST] Processing event: {event_title}")
        print(f"      Markets in event: {len(markets)}")
        
        total_holders_collected = 0
        
        for idx, market in enumerate(markets, 1):
            question = market.get('question', '')
            condition_id = market.get('conditionId')
            
            if not condition_id:
                print(f"      [WARN]  Market {idx} missing condition ID: {question[:50]}...")
                continue
            
            # --- Holder Search Strategy (Implemented per   2.2 and   3.1) ---
            strategy = HeuristicsConfig.HOLDER_STRATEGY
            holders_to_fetch = []
            
            if strategy == "TOP":
                # Only fetch the first page (top holders)
                holders_to_fetch.append(api.get_market_holders(condition_id, limit=HeuristicsConfig.HOLDERS_LIMIT, offset=0))
            
            elif strategy == "BULK":
                # Fetch N pages sequentially
                for page in range(HeuristicsConfig.HOLDER_PAGES):
                    holders_to_fetch.append(api.get_market_holders(condition_id, limit=HeuristicsConfig.HOLDERS_LIMIT, offset=page * HeuristicsConfig.HOLDERS_LIMIT))
            
            elif strategy == "MIXED":
                # TOP page + 1 Random page from deeper offset
                holders_to_fetch.append(api.get_market_holders(condition_id, limit=HeuristicsConfig.HOLDERS_LIMIT, offset=0))
                random_offset = random.randint(HeuristicsConfig.HOLDERS_LIMIT, HeuristicsConfig.HOLDER_RANDOM_OFFSET_MAX)
                holders_to_fetch.append(api.get_market_holders(condition_id, limit=HeuristicsConfig.HOLDERS_LIMIT, offset=random_offset))
            
            print(f"      [STATS] Market {idx}/{len(markets)}: Fetching holders using strategy '{strategy}'...")
            
            # Execute fetch tasks
            pages_results = await asyncio.gather(*holders_to_fetch)
            
            # Register all unique holders across all fetched pages
            for page_holders in pages_results:
                if not page_holders: continue
                
                for holder in page_holders:
                    wallet = holder.get('proxyWallet')
                    name = holder.get('name', wallet[:8] if wallet else 'Unknown')
                    
                    if wallet and wallet not in self.registry:
                        self.registry[wallet] = {
                            'name': name,
                            'wallet': wallet,
                            'positions_fetched': False
                        }
                        total_holders_collected += 1
        
        print(f"   [OK] Collected {total_holders_collected} unique new holders from this event\n")
        
    async def _fetch_all_positions(self, api: PolymarketAPI):
        """Fetch positions for whales in batches, prioritizing top holders"""
        
        total = len(self.registry)
        
        # [OK] Ask user how many to process
        if total > 500:
            print(f"\n[WARN] WARNING: {total} whales found!")
            print(f"   Fetching all would take ~{(total * 4) / 60:.0f} minutes")
            
            max_whales = input(f"\n   How many whales to analyze? (1-{total}, default=200): ").strip()
            
            try:
                max_whales = int(max_whales) if max_whales else 200
                max_whales = min(max_whales, total)
            except:
                max_whales = 200
            
            print(f"   [INFO] Processing top {max_whales} whales only")
            
            # Limit registry to first N whales
            registry_items = list(self.registry.items())[:max_whales]
        else:
            registry_items = list(self.registry.items())
            max_whales = total
        
        print(f"   [INFO] Fetching positions for {max_whales} whales...")
        print(f"   [TIME] Estimated time: ~{(max_whales * 4) / 60:.0f} minutes")
        print(f"   [TIME] Rate limit: {api.REQUEST_DELAY}s delay, {api.MAX_CONCURRENT_REQUESTS} concurrent\n")
        
        # Process in batches (keep small to match MAX_CONCURRENT_REQUESTS)
        BATCH_SIZE = 10
        
        for batch_num in range(0, len(registry_items), BATCH_SIZE):
            batch = registry_items[batch_num:batch_num + BATCH_SIZE]
            batch_end = min(batch_num + BATCH_SIZE, len(registry_items))
            
            print(f"   [BATCH] Batch {batch_num//BATCH_SIZE + 1}/{(len(registry_items) + BATCH_SIZE - 1)//BATCH_SIZE}")
            print(f"      Whales {batch_num + 1}-{batch_end}")
            
            tasks = []
            for wallet, info in batch:
                tasks.append(api.fetch_whale_positions(wallet, info['name']))
            
            results = await asyncio.gather(*tasks)
            
            # Store results
            success_count = 0
            for result in results:
                wallet = result['wallet']
                if wallet in self.registry:
                    self.registry[wallet]['active_raw'] = result['active']
                    self.registry[wallet]['closed_raw'] = result['closed']
                    self.registry[wallet]['positions_fetched'] = True
                    
                    if result['active'] or result['closed']:
                        success_count += 1
            
            print(f"      [OK] Fetched: {success_count}/{len(batch)}\n")
            
            # Brief pause between batches   semaphore + REQUEST_DELAY already throttles per-request
            # BUG FIX: was 30s, which caused 10-min timeout to fire after only ~14 batches (~140 whales)
            if batch_end < len(registry_items):
                print(f"      [PAUSE] Batch cooldown {HeuristicsConfig.BATCH_COOLDOWN}s...")
                await asyncio.sleep(HeuristicsConfig.BATCH_COOLDOWN)
        
        # Final summary
        total_fetched = sum(1 for info in self.registry.values() 
                        if info.get('positions_fetched') and 
                        (info.get('active_raw') or info.get('closed_raw')))
        
        print(f"\n   [OK] Successfully fetched: {total_fetched}/{max_whales} whales")
            

    def _analyze_whales(self) -> Dict:
        """Analyze all whales and classify them"""
        expertise_summary = []
        active_positions = []
        closed_positions = []
        
        print(f"\n[DEBUG] DEBUG: Analyzing {len(self.registry)} whales...")
        
        # [OK] Diagnostic counters
        debug_stats = {
            'total_whales': len(self.registry),
            'positions_fetched': 0,
            'failed_entry_gate': 0,
            'failed_qualification': 0,
            'passed_all_filters': 0,
            'entry_gate_reasons': {},
            'qualification_reasons': {}
        }
        
        for idx, (wallet, info) in enumerate(self.registry.items(), 1):
            whale_name = info['name']
            
            if self.debug:
                print(f"\n{'='*60}")
                print(f"[WHALE] Whale {idx}/{len(self.registry)}: {whale_name}")
                print(f"   Wallet: {wallet[:10]}...")
            
            # Check if positions were fetched
            if not info.get('positions_fetched'):
                if self.debug:
                    print(f"   [ERROR] Positions not fetched (rate limited or error)")
                continue
            
            debug_stats['positions_fetched'] += 1
            
            # [OK] Print raw data sample
            if self.debug:
                active_count = len(info.get('active_raw', []))
                closed_count = len(info.get('closed_raw', []))
                print(f"   [BATCH] Raw data: {active_count} active, {closed_count} closed positions")
            
            # Process positions
            whale_data = self._process_whale_positions(info)
            
            # [OK] Print processed data
            if self.debug:
                print(f"   [STATS] Processed data:")
                print(f"      - All positions: {len(whale_data['all_positions'])}")
                print(f"      - Topic positions: {len(whale_data['all_topic_positions'])}")
                print(f"      - Closed topic: {len(whale_data['closed_topic_positions'])}")
                print(f"      - Active topic: {len(whale_data['active_topic_positions'])}")
            
            # Entry gate check
            entry_result = EntryGate.evaluate(whale_data)
            
            if self.debug:
                print(f"   [DOOR] Entry Gate: {'[OK] PASSED' if entry_result['passed'] else '[ERROR] FAILED'}")
                print(f"      Type: {entry_result['entry_type']}")
                print(f"      Reason: {entry_result['reason']}")
            
            if not entry_result['passed']:
                debug_stats['failed_entry_gate'] += 1
                reason = entry_result['reason']
                debug_stats['entry_gate_reasons'][reason] = debug_stats['entry_gate_reasons'].get(reason, 0) + 1
                continue
            
            # Calculate metrics
            metrics = MetricsCalculator.calculate(whale_data)
            win_rates = WinRateAnalyzer.analyze(whale_data)
            
            # [INFO] Print metrics
            if self.debug:
                print(f"   [METRICS] Metrics:")
                print(f"      - Profit Factor: {metrics['profit_factor']:.2f}")
                print(f"      - ROI: {metrics['roi']:.1f}%")
                print(f"      - Concentration: {metrics['concentration']:.1f}%")
                print(f"      - Topic Positions: {metrics['topic_positions']}")
                print(f"      - Historical Total: {metrics['historical_total']}")
                print(f"      - Total Exposure: ${metrics['total_exposure']:,.0f}")
                print(f"      - Net PnL: ${metrics['net_pnl']:,.0f}")
            
            # Qualification filters
            passed_qual, qual_reason = QualificationFilters.passes(metrics)
            
            if self.debug:
                print(f"   [GRAD] Qualification: {'[OK] PASSED' if passed_qual else '[ERROR] FAILED'}")
                if not passed_qual:
                    print(f"      Reason: {qual_reason}")
            
            if not passed_qual:
                debug_stats['failed_qualification'] += 1
                debug_stats['qualification_reasons'][qual_reason] = debug_stats['qualification_reasons'].get(qual_reason, 0) + 1
                continue
            
            debug_stats['passed_all_filters'] += 1
            
            # Classify
            classification = WhaleClassifier.classify(metrics, win_rates)
            
            if self.debug:
                print(f"   [CROWN] Classification: {classification['flag']}")
                print(f"      Tier: {classification['tier']}")
                print(f"      Priority: {classification['priority']}")
                print(f"      Insider Prob: {classification['insider_probability']}%")
            
            # Build summary row (existing code...)
            expertise_summary.append({
                'Whale_Name': info['name'],
                'Wallet': wallet,
                'Entry_Type': entry_result['entry_type'],
                'Tier': classification['tier'],
                'Flag': classification['flag'],
                'Priority': classification['priority'],
                'Insider_Probability': f"{classification['insider_probability']}%",
                'Reasoning': classification['reasoning'],
                'Net_PnL': metrics['net_pnl'],
                'Total_Exposure': metrics['total_exposure'],
                'ROI': metrics['roi'],
                'Profit_Factor': metrics['profit_factor'],
                'Overall_Win_Rate': win_rates['overall_win_rate'],
                'Topic_Win_Rate': win_rates['topic_win_rate'],
                'Win_Rate_Delta': win_rates['win_rate_delta'],
                'Topic_Specialist': 'YES' if win_rates['is_topic_specialist'] else 'No',
                'Topic_Bets': metrics['topic_positions'],
                'Total_Historical_Bets': win_rates['overall_total'],
                'Concentration': metrics['concentration'],
                'Topic_Confidence': win_rates['topic_confidence'],
                'Reliability': metrics['reliability_score']
            })
            
            # Collect positions (existing code...)
            for pos in whale_data['significant_active']:
                # BUG FIX: API returns 'currentValue', not 'value' (confirmed by live test)
                current_value = pos['raw'].get('currentValue', pos['raw'].get('value', 0))
                active_positions.append({
                    'Whale_Name': info['name'],
                    'Wallet': wallet,
                    'Market': pos['raw'].get('title', 'Unknown'),
                    'Spent': pos['spent'],
                    'Current_Value': current_value,
                    'Unrealized_PnL': current_value - pos['spent']
                })
            
            for pos in whale_data['significant_closed']:
                closed_positions.append({
                    'Whale_Name': info['name'],
                    'Wallet': wallet,
                    'Market': pos['raw'].get('title', 'Unknown'),
                    'Cost': pos['cost'],
                    'PnL': pos['pnl'],
                    'Profit_Pct': pos['profit_pct']
                })
        
        # Final debug summary
        print(f"\n{'='*60}")
        print(f"DEBUG SUMMARY")
        print(f"{'='*60}")
        print(f"Total whales in registry: {debug_stats['total_whales']}")
        print(f"Positions successfully fetched: {debug_stats['positions_fetched']}")
        print(f"Failed entry gate: {debug_stats['failed_entry_gate']}")
        print(f"Failed qualification: {debug_stats['failed_qualification']}")
        print(f"   [OK] PASSED ALL FILTERS: {debug_stats['passed_all_filters']}")
        
        if debug_stats['entry_gate_reasons']:
            print(f"\nEntry Gate Failure Reasons:")
            for reason, count in sorted(debug_stats['entry_gate_reasons'].items(), key=lambda x: x[1], reverse=True):
                print(f"  - {reason}: {count} whales")
        
        if debug_stats['qualification_reasons']:
            print(f"\nQualification Failure Reasons:")
            for reason, count in sorted(debug_stats['qualification_reasons'].items(), key=lambda x: x[1], reverse=True):
                print(f"  - {reason}: {count} whales")
        
        print(f"{'='*60}\n")
        
        # Sort by priority
        expertise_summary.sort(key=lambda x: x['Priority'], reverse=True)
        
        return {
            'expertise': expertise_summary,
            'active': active_positions,
            'closed': closed_positions
        }
    
    def _is_topic_position(self, title: str, event_slug: str) -> bool:
        """
        Determine if a position is on-topic via TWO paths:
          1. Title text match (query keywords in market title)
          2. EventSlug match (position belongs to an event we already identified as on-topic)
        
        Path 2 is the reliable fallback: even if the market title like
        'By March 31?' doesn't contain 'iran', if its eventSlug is
        'will-iran-strike-israel-by-march-31' then it IS on topic.
        """
        # Path 1: Title text match
        if self.matcher.matches(title):
            return True
        # Path 2: EventSlug membership check
        if event_slug and event_slug in self.known_event_slugs:
            return True
        return False

    def _process_whale_positions(self, info: Dict) -> Dict:
        """Process raw positions into structured data"""

        active_raw = info.get('active_raw', [])
        closed_raw = info.get('closed_raw', [])
        
        # [OK] DEBUG: Print first position sample
        if self.debug and (active_raw or closed_raw):
            print(f"\n   [DEBUG] RAW DATA SAMPLE:")
            if active_raw:
                sample = active_raw[0]
                print(f"      Active position fields: {list(sample.keys())}")
                print(f"      Title: {sample.get('title', 'N/A')}")
                print(f"      InitialValue: {sample.get('initialValue', 'N/A')}")
            if closed_raw:
                sample = closed_raw[0]
                print(f"      Closed position fields: {list(sample.keys())}")
                print(f"      Title: {sample.get('title', 'N/A')}")
                print(f"      TotalBought: {sample.get('totalBought', 'N/A')}")
                print(f"      PnL: {sample.get('realizedPnl', 'N/A')}")
        
        # Rest of processing code...
        # (keep existing code)
        
        # Process active positions
        all_active = []
        topic_active = []
        significant_active = []
        
        for ab in active_raw:
            market_title = ab.get('title', '')
            spent = float(ab.get('initialValue', 0))
            
            pos_data = {'spent': spent, 'raw': ab}
            all_active.append(pos_data)
            
            event_slug = ab.get('eventSlug', '')
            if self._is_topic_position(market_title, event_slug):
                topic_active.append(pos_data)
                
                if spent >= HeuristicsConfig.MIN_POSITION_FOR_DISPLAY:
                    significant_active.append(pos_data)
        
        # Process closed positions
        all_closed = []
        topic_closed = []
        significant_closed = []
        
        for cb in closed_raw:
            market_title = cb.get('title', '')
            
            # Parse financials
            total_bought = float(cb.get('totalBought', 0))
            avg_price = float(cb.get('avgPrice', 0))
            cost = total_bought * avg_price
            pnl = float(cb.get('realizedPnl', 0))
            
            # Validation: skip zero-cost positions
            # BUG FIX: 'invested' field does NOT exist in the API (confirmed by live test)
            # Fallback: use totalBought directly as a dollar estimate
            if cost == 0:
                if pnl == 0:
                    continue
                cost = float(cb.get('totalBought', 0))
                if cost == 0:
                    continue
            
            profit_pct = (pnl / cost * 100) if cost > 0 else 0
            
            pos_data = {
                'cost': cost,
                'pnl': pnl,
                'profit_pct': profit_pct,
                'raw': cb
            }
            
            all_closed.append(pos_data)
            
            event_slug = cb.get('eventSlug', '')
            if self._is_topic_position(market_title, event_slug):
                topic_closed.append(pos_data)
                
                if cost >= HeuristicsConfig.MIN_POSITION_FOR_DISPLAY:
                    significant_closed.append(pos_data)
        
        return {
            'all_positions': all_active + all_closed,
            'all_active_positions': all_active,
            'all_historical_positions': all_closed,
            'active_topic_positions': topic_active,
            'closed_topic_positions': topic_closed,
            'all_topic_positions': topic_active + topic_closed,
            'significant_active': significant_active,
            'significant_closed': significant_closed
        }
    
    def _export_to_excel(self, results: Dict):
        """Export results to Excel"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        query_clean = self.matcher.raw.replace(' ', '_').replace(',', '')
        filename = f"OSINT_INSIDER_REPORT_{query_clean}_{timestamp}.xlsx"
        
        # [OK] Check if we have any data to export
        has_expertise = len(results['expertise']) > 0
        has_active = len(results['active']) > 0
        has_closed = len(results['closed']) > 0
        
        if not (has_expertise or has_active or has_closed):
            print("\n[WARN] WARNING: No data to export!")
            print("   Possible reasons:")
            print("   - All whales were rate limited (429 errors)")
            print("   - No whales passed entry gate filters")
            print("   - No whales passed qualification filters")
            return
        
        try:
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                # Sheet 1: Expertise Summary
                if has_expertise:
                    df_expertise = pd.DataFrame(results['expertise'])
                    df_expertise.to_excel(writer, sheet_name='Expertise_Summary', index=False)
                
                # Sheet 2: Active Positions
                if has_active:
                    df_active = pd.DataFrame(results['active'])
                    df_active.to_excel(writer, sheet_name='Active_Positions', index=False)
                
                # Sheet 3: Closed Positions
                if has_closed:
                    df_closed = pd.DataFrame(results['closed'])
                    df_closed.to_excel(writer, sheet_name='Closed_Positions', index=False)
                
                # [OK] If no sheets created, add placeholder
                if not (has_expertise or has_active or has_closed):
                    df_placeholder = pd.DataFrame({
                        'Message': ['No data available - see console for details']
                    })
                    df_placeholder.to_excel(writer, sheet_name='No_Data', index=False)
            
            print(f"\n[OK] Report saved: {filename}")
            print(f"   Whales identified: {len(results['expertise'])}")
            print(f"   Active positions: {len(results['active'])}")
            print(f"   Closed positions: {len(results['closed'])}")
            
        except Exception as e:
            print(f"\n[ERROR] Error creating Excel file: {e}")


# --- Main Execution ---
import sys

async def main():
    """Main entry point"""
    print("\n[WHALE] POLYMARKET INSIDER WHALE DETECTOR")
    print("=" * 60)
     # [OK] Windows: Prevent sleep during execution
    if sys.platform == 'win32':
        try:
            import ctypes
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            )
            print("[LOCK] Sleep mode disabled during execution")
        except:
            print("[WARN] Could not disable sleep mode - keep PC awake manually!")

    user_query = input("\nEnter your query: ").strip()
    
    if not user_query:
        print("[ERROR] Query cannot be empty")
        return
    
    debug_mode = input("Enable debug mode? (y/n, default=y): ").strip().lower()
    debug = debug_mode != 'n'
    
    use_regex_input = input("USE REGEX? (y/n, default=n): ").strip().lower()
    use_regex = use_regex_input == 'y'
    
    # --- STARTUP CONNECTIVITY TEST ---
    print("\n[CONN] Testing API connectivity...")
    async with PolymarketAPI() as test_api:
        test_result = await test_api.search_events("bitcoin", limit=1)
        if test_result:
            print(f"   [OK] API reachable   got {len(test_result)} result(s)")
        else:
            print("   [WARN] API returned no results for 'bitcoin'   check connection or VPN")
            print("   Proceeding anyway...")
    
    engine = PolymarketOSINTEngine(user_query, use_regex=use_regex, debug=debug)
    await engine.run_mission()


if __name__ == "__main__":
    asyncio.run(main())
