"""
rules.py
Whale classification logic and heuristics
"""

from typing import Dict, List, Tuple


class HeuristicsConfig:
    """Centralized configuration for all thresholds.
    
    Thresholds are intentionally LOW to ensure real wallets with modest
    activity are captured. Raise them once you confirm data is flowing.
    """
    
    # Entry Gate - Smoking Gun (single large bet on topic)
    SMOKING_GUN_SIZE = 1000          # was 5000
    SMOKING_GUN_PROFIT_PCT = 30      # was 60 — easier to qualify

    # Entry Gate - Heavy Hitter (systematic operator)
    HEAVY_HITTER_EXPOSURE = 3000     # was 15000
    HEAVY_HITTER_MIN_BETS = 3        # was 8
    
    # Qualification Filters (must pass to be analyzed)
    MIN_ONTOPIC_POSITIONS = 2        # was 5
    MIN_TOTAL_EXPOSURE = 3000        # was 15000
    MIN_HISTORICAL_TRADES = 2        # was 5
    MIN_PROFIT_FACTOR = 1.1          # was 1.5
    MIN_ROI = 5.0                    # was 8.0
    MIN_CONCENTRATION = 20.0         # was 50.0
    
    # Display threshold for positions
    MIN_POSITION_FOR_DISPLAY = 500   # was 5000


class EntryGate:
    """First filter - catches smoking guns and heavy hitters"""
    
    @staticmethod
    def evaluate(whale_data: Dict) -> Dict:
        """
        Check if whale passes entry criteria
        
        Args:
            whale_data: Dict with 'closed_topic_positions', 'active_topic_positions', 'all_topic_positions'
            
        Returns:
            {'passed': bool, 'entry_type': str, 'reason': str}
        """
        # PATH 1: Smoking Gun - Single massive bet
        smoking_gun_closed = any(
            pos['cost'] >= HeuristicsConfig.SMOKING_GUN_SIZE 
            and pos['profit_pct'] >= HeuristicsConfig.SMOKING_GUN_PROFIT_PCT
            for pos in whale_data.get('closed_topic_positions', [])
        )
        
        smoking_gun_active = any(
            pos['spent'] >= HeuristicsConfig.SMOKING_GUN_SIZE
            for pos in whale_data.get('active_topic_positions', [])
        )
        
        if smoking_gun_closed or smoking_gun_active:
            return {
                'passed': True,
                'entry_type': 'SMOKING_GUN',
                'reason': f'Single bet ≥${HeuristicsConfig.SMOKING_GUN_SIZE:,}'
            }
        
        # PATH 2: Heavy Hitter - Systematic operator
        total_exposure = (
            sum(p['cost'] for p in whale_data.get('closed_topic_positions', [])) +
            sum(p['spent'] for p in whale_data.get('active_topic_positions', []))
        )
        topic_bet_count = len(whale_data.get('all_topic_positions', []))
        
        if (total_exposure >= HeuristicsConfig.HEAVY_HITTER_EXPOSURE 
            and topic_bet_count >= HeuristicsConfig.HEAVY_HITTER_MIN_BETS):
            return {
                'passed': True,
                'entry_type': 'HEAVY_HITTER',
                'reason': f'${total_exposure:,.0f} across {topic_bet_count} bets'
            }
        
        return {
            'passed': False,
            'entry_type': 'NONE',
            'reason': 'Below entry thresholds'
        }


class MetricsCalculator:
    """Calculate all whale performance metrics"""
    
    @staticmethod
    def calculate(whale_data: Dict) -> Dict:
        """
        Calculate comprehensive metrics for a whale
        
        Args:
            whale_data: Complete whale position data
            
        Returns:
            Dict of calculated metrics
        """
        closed_topic = whale_data.get('closed_topic_positions', [])
        active_topic = whale_data.get('active_topic_positions', [])
        all_closed = whale_data.get('all_historical_positions', [])
        
        # Basic counts
        topic_positions = len(closed_topic) + len(active_topic)
        historical_total = len(all_closed)
        
        # Financial metrics
        wins_pnl = sum(p['pnl'] for p in closed_topic if p['pnl'] > 0)
        losses_pnl = sum(abs(p['pnl']) for p in closed_topic if p['pnl'] < 0)
        net_pnl = sum(p['pnl'] for p in closed_topic)
        
        total_invested = sum(p['cost'] for p in closed_topic)
        total_exposure = total_invested + sum(p['spent'] for p in active_topic)
        
        # Profit factor
        if losses_pnl > 0:
            profit_factor = wins_pnl / losses_pnl
        elif wins_pnl > 0:
            profit_factor = 999.0  # Perfect record
        else:
            profit_factor = 0.0
        
        # ROI
        roi = (net_pnl / total_invested * 100) if total_invested > 0 else 0.0
        
        # Concentration
        total_bets = len(whale_data.get('all_positions', []))
        concentration = (topic_positions / total_bets * 100) if total_bets > 0 else 0.0
        
        # Reliability score
        reliability_score = MetricsCalculator._calculate_reliability(
            historical_total, topic_positions
        )
        
        return {
            'topic_positions': topic_positions,
            'historical_total': historical_total,
            'net_pnl': net_pnl,
            'wins_pnl': wins_pnl,
            'losses_pnl': losses_pnl,
            'profit_factor': profit_factor,
            'roi': roi,
            'total_exposure': total_exposure,
            'concentration': concentration,
            'reliability_score': reliability_score
        }
    
    @staticmethod
    def _calculate_reliability(historical_trades: int, topic_positions: int) -> float:
        """
        Calculate reliability score (0.0 - 1.0) based on sample size
        
        Args:
            historical_trades: Total closed positions
            topic_positions: Topic-specific positions
            
        Returns:
            Reliability score
        """
        # Sample size confidence
        if historical_trades < 10:
            sample_score = historical_trades / 10
        else:
            sample_score = min(1.0, historical_trades / 50)
        
        # Topic focus bonus
        if topic_positions >= 20:
            focus_score = 1.0
        elif topic_positions >= 10:
            focus_score = 0.8
        else:
            focus_score = 0.6
        
        return sample_score * focus_score


class WinRateAnalyzer:
    """Dual win rate analysis - overall vs topic"""
    
    @staticmethod
    def analyze(whale_data: Dict) -> Dict:
        """
        Calculate overall and topic-specific win rates
        
        Args:
            whale_data: Complete whale data
            
        Returns:
            Dict with win rate metrics and comparisons
        """
        all_closed = whale_data.get('all_historical_positions', [])
        topic_closed = whale_data.get('closed_topic_positions', [])
        
        # Overall win rate (all markets)
        overall_wins = sum(1 for p in all_closed if p['pnl'] > 0)
        overall_total = len(all_closed)
        overall_win_rate = (overall_wins / overall_total * 100) if overall_total > 0 else 0
        overall_confidence = overall_win_rate * (1 - 1/max(overall_total, 1))
        
        # Topic win rate
        topic_wins = sum(1 for p in topic_closed if p['pnl'] > 0)
        topic_total = len(topic_closed)
        topic_win_rate = (topic_wins / topic_total * 100) if topic_total > 0 else 0
        topic_confidence = topic_win_rate * (1 - 1/max(topic_total, 1))
        
        # Delta analysis (THE KILLER METRIC)
        win_rate_delta = topic_win_rate - overall_win_rate
        is_topic_specialist = win_rate_delta > 15
        
        relative_improvement = (
            (win_rate_delta / overall_win_rate * 100) 
            if overall_win_rate > 0 else 0
        )
        
        return {
            'overall_win_rate': overall_win_rate,
            'overall_wins': overall_wins,
            'overall_total': overall_total,
            'overall_confidence': overall_confidence,
            'topic_win_rate': topic_win_rate,
            'topic_wins': topic_wins,
            'topic_total': topic_total,
            'topic_confidence': topic_confidence,
            'win_rate_delta': win_rate_delta,
            'relative_improvement': relative_improvement,
            'is_topic_specialist': is_topic_specialist
        }


class QualificationFilters:
    """Check if whale meets minimum requirements"""
    
    @staticmethod
    def passes(metrics: Dict) -> Tuple[bool, str]:
        """
        Check if whale passes qualification filters.

        Two-path logic:
          - Has closed positions → enforce ALL filters (topic count, exposure,
            concentration, historical trades, profit factor, ROI)
          - Active-only (no closed history) → enforce only structural filters
            (topic count, exposure, concentration). Skipping performance metrics
            avoids incorrectly rejecting PURE ACTIVE whales who have never
            closed a position in our fetched window.

        BUG FIX: Previously all 6 checks ran unconditionally, meaning any whale
        with zero closed positions had profit_factor=0, roi=0, historical=0 and
        was guaranteed to fail — even if they had a $10k active position.
        
        Args:
            metrics: Calculated metrics
            
        Returns:
            (passed: bool, reason: str)
        """
        # ── Always-required structural checks ──────────────────────────────
        structural_checks = [
            (metrics['topic_positions'] >= HeuristicsConfig.MIN_ONTOPIC_POSITIONS,
             f"Topic positions: {metrics['topic_positions']} < {HeuristicsConfig.MIN_ONTOPIC_POSITIONS}"),
            
            (metrics['total_exposure'] >= HeuristicsConfig.MIN_TOTAL_EXPOSURE,
             f"Total exposure: ${metrics['total_exposure']:,.0f} < ${HeuristicsConfig.MIN_TOTAL_EXPOSURE:,}"),
            
            (metrics['concentration'] >= HeuristicsConfig.MIN_CONCENTRATION,
             f"Concentration: {metrics['concentration']:.1f}% < {HeuristicsConfig.MIN_CONCENTRATION}%"),
        ]
        
        for passed, reason in structural_checks:
            if not passed:
                return False, reason
        
        # ── Performance checks only when closed history exists ─────────────
        if metrics['historical_total'] > 0:
            perf_checks = [
                (metrics['historical_total'] >= HeuristicsConfig.MIN_HISTORICAL_TRADES,
                 f"Historical trades: {metrics['historical_total']} < {HeuristicsConfig.MIN_HISTORICAL_TRADES}"),
                
                (metrics['profit_factor'] >= HeuristicsConfig.MIN_PROFIT_FACTOR,
                 f"Profit factor: {metrics['profit_factor']:.2f} < {HeuristicsConfig.MIN_PROFIT_FACTOR}"),
                
                (metrics['roi'] >= HeuristicsConfig.MIN_ROI,
                 f"ROI: {metrics['roi']:.1f}% < {HeuristicsConfig.MIN_ROI}%"),
            ]
            for passed, reason in perf_checks:
                if not passed:
                    return False, reason
        
        return True, "All filters passed"


class WhaleClassifier:
    """Tiered classification system"""
    
    @staticmethod
    def classify(metrics: Dict, win_rates: Dict) -> Dict:
        """
        Classify whale into tiers based on metrics
        
        Args:
            metrics: Performance metrics
            win_rates: Win rate analysis
            
        Returns:
            Classification result with tier, flag, priority, reasoning
        """
        pf = metrics['profit_factor']
        conc = metrics['concentration']
        trades = metrics['topic_positions']
        pnl = metrics['net_pnl']
        exposure = metrics['total_exposure']
        reliability = metrics['reliability_score']
        
        topic_conf = win_rates['topic_confidence']
        win_delta = win_rates['win_rate_delta']
        is_specialist = win_rates['is_topic_specialist']
        
        # 💀 TIER 0: EXTREME OUTLIER
        if all([
            pf > 10.0,
            conc > 80,
            trades >= 15,
            pnl > 100000,
            exposure > 150000,
            reliability >= 0.8,
            (win_delta > 25 or topic_conf > 80)
        ]):
            return {
                'tier': 'EXTREME_OUTLIER',
                'flag': '💀 EXTREME OUTLIER - INVESTIGATE IMMEDIATELY',
                'priority': 10,
                'reasoning': f'PF={pf:.1f}, Win Δ={win_delta:+.1f}%, ${pnl:,.0f} profit',
                'insider_probability': 95
            }
        
        # 🚨 TIER 1: SUPER HIGH
        elif all([
            pf > 3.5,
            conc > 70,
            topic_conf > 60,
            trades >= 20,
            pnl > 50000,
            exposure > 100000,
            reliability >= 0.8,
            (win_delta > 15 or is_specialist)
        ]):
            return {
                'tier': 'SUPER_HIGH',
                'flag': '🚨 PROBABLE INSIDER',
                'priority': 5,
                'reasoning': f'PF={pf:.1f}, Win Δ={win_delta:+.1f}%, Conc={conc:.0f}%',
                'insider_probability': 80
            }
        
        # ⭐ TIER 2: HIGH
        elif all([
            pf > 2.5,
            conc > 60,
            topic_conf > 55,
            trades >= 12,
            pnl > 25000,
            exposure > 50000,
            reliability >= 0.7,
            win_delta > 5
        ]):
            return {
                'tier': 'HIGH',
                'flag': '⭐ STRONG INFORMATION EDGE',
                'priority': 4,
                'reasoning': f'PF={pf:.1f}, Win Δ={win_delta:+.1f}%',
                'insider_probability': 60
            }
        
        # ✅ TIER 3: MEDIUM
        elif all([
            pf > 2.0,
            conc > 50,
            topic_conf > 50,
            trades >= 8,
            pnl > 10000,
            exposure > 30000,
            reliability >= 0.6
        ]):
            return {
                'tier': 'MEDIUM',
                'flag': '✅ SKILLED OPERATOR',
                'priority': 3,
                'reasoning': f'PF={pf:.1f}, {trades} bets, ${pnl:,.0f}',
                'insider_probability': 40
            }
        
        # 📊 TIER 4: WATCH LIST
        elif all([
            pf > 1.5,
            conc > 40,
            trades >= 5,
            pnl > 5000,
            exposure > 15000
        ]):
            return {
                'tier': 'WATCH',
                'flag': '📊 WATCH LIST - Emerging Pattern',
                'priority': 2,
                'reasoning': f'{trades} bets, needs more data',
                'insider_probability': 20
            }
        
        # ⚠️ TIER 5: MARGINAL
        else:
            return {
                'tier': 'MARGINAL',
                'flag': '⚠️ MARGINAL',
                'priority': 1,
                'reasoning': 'Weak signals',
                'insider_probability': 5
            }
