"""Decision engine for automated campaign management.

This module contains the logic for evaluating seller performance and making
automated decisions about campaign budgets, ROAS targets, and pausing.
"""

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

import pandas as pd

logger = logging.getLogger(__name__)

class DecisionType(Enum):
    """Types of campaign decisions."""
    KEEP = "keep"
    SCALE = "scale"  # Increase budget
    CUT = "cut"      # Decrease budget or increase tROAS
    PAUSE = "pause"  # Pause campaign

@dataclass
class CampaignDecision:
    """Represents a decision about a campaign."""
    campaign_id: str
    campaign_name: str
    seller: str
    price_bucket: str
    decision: DecisionType
    current_budget: float
    new_budget: Optional[float] = None
    current_troas: Optional[float] = None
    new_troas: Optional[float] = None
    reason: str = ""
    confidence: float = 0.0

@dataclass
class DecisionRules:
    """Configuration for decision rules."""
    # ROAS thresholds
    min_roas: float = 2.0
    target_roas: float = 4.0
    excellent_roas: float = 6.0
    
    # Volume thresholds
    min_impressions: int = 1000
    min_conversions: int = 5
    high_volume_impressions: int = 10000
    
    # Budget adjustment factors
    scale_factor: float = 1.5  # Multiply budget by this when scaling
    cut_factor: float = 0.7    # Multiply budget by this when cutting
    
    # tROAS adjustment factors
    troas_increase_factor: float = 1.2  # Increase tROAS by this factor
    troas_decrease_factor: float = 0.9  # Decrease tROAS by this factor
    
    # Minimum data requirements
    min_days_data: int = 7
    min_weekly_impressions: int = 500

class DecisionEngine:
    """Engine for making automated campaign decisions."""
    
    def __init__(self, rules: Optional[DecisionRules] = None):
        """Initialize decision engine with rules."""
        self.rules = rules or DecisionRules()
    
    def evaluate_seller_performance(
        self, 
        performance_data: pd.DataFrame,
        current_campaigns: Dict[str, Dict]
    ) -> List[CampaignDecision]:
        """
        Evaluate seller performance and generate campaign decisions.
        
        Args:
            performance_data: DataFrame with label performance data
            current_campaigns: Dict of current campaign info
            
        Returns:
            List of campaign decisions
        """
        decisions = []
        
        # Group by seller and price bucket
        grouped = performance_data.groupby(['seller', 'price_bucket'])
        
        for (seller, price_bucket), group in grouped:
            # Calculate aggregated metrics for this seller/bucket combination
            metrics = self._calculate_metrics(group)
            
            if not self._has_sufficient_data(metrics):
                continue
            
            # Find corresponding campaign
            campaign_info = self._find_campaign(seller, price_bucket, current_campaigns)
            if not campaign_info:
                continue
            
            # Make decision based on performance
            decision = self._make_decision(metrics, campaign_info)
            if decision:
                decisions.append(decision)
        
        return decisions
    
    def _calculate_metrics(self, group: pd.DataFrame) -> Dict[str, float]:
        """Calculate performance metrics for a seller/bucket group."""
        return {
            'total_impressions': group['impressions'].sum() if 'impressions' in group.columns else 0,
            'total_clicks': group['clicks'].sum() if 'clicks' in group.columns else 0,
            'total_conversions': group['conversions'].sum() if 'conversions' in group.columns else 0,
            'total_value': group['value'].sum() if 'value' in group.columns else 0,
            'total_cost': group['cost'].sum() if 'cost' in group.columns else 0,
            'avg_roas': group['roas'].mean() if 'roas' in group.columns else 0,
            'avg_ctr': group['ctr'].mean() if 'ctr' in group.columns else 0,
            'avg_conversion_rate': group['conversion_rate'].mean() if 'conversion_rate' in group.columns else 0,
            'avg_cpa': group['cpa'].mean() if 'cpa' in group.columns else 0,
            'days_active': group['date'].nunique() if 'date' in group.columns else 0,
            'recent_impressions': group[group['date'] >= date.today() - timedelta(days=7)]['impressions'].sum() if 'impressions' in group.columns and 'date' in group.columns else 0,
            'recent_conversions': group[group['date'] >= date.today() - timedelta(days=7)]['conversions'].sum() if 'conversions' in group.columns and 'date' in group.columns else 0
        }
    
    def _has_sufficient_data(self, metrics: Dict[str, float]) -> bool:
        """Check if there's sufficient data to make a decision."""
        return (
            metrics['days_active'] >= self.rules.min_days_data and
            metrics['total_impressions'] >= self.rules.min_impressions and
            metrics['recent_impressions'] >= self.rules.min_weekly_impressions
        )
    
    def _find_campaign(
        self, 
        seller: str, 
        price_bucket: str, 
        current_campaigns: Dict[str, Dict]
    ) -> Optional[Dict[str, any]]:
        """Find campaign info for a seller/bucket combination."""
        # Look for campaigns that match seller and price bucket
        for campaign_id, campaign_info in current_campaigns.items():
            if (campaign_info.get('seller') == seller and 
                campaign_info.get('price_bucket') == price_bucket):
                return campaign_info
        return None
    
    def _make_decision(
        self, 
        metrics: Dict[str, float], 
        campaign_info: Dict[str, any]
    ) -> Optional[CampaignDecision]:
        """Make a decision based on performance metrics."""
        roas = metrics['avg_roas']
        impressions = metrics['total_impressions']
        conversions = metrics['total_conversions']
        recent_impressions = metrics['recent_impressions']
        
        current_budget = campaign_info.get('budget', 0.0)
        current_troas = campaign_info.get('troas', 0.0)
        
        # Decision logic
        if roas < self.rules.min_roas and conversions > 0:
            # Poor performance - cut budget or pause
            if recent_impressions < self.rules.min_weekly_impressions:
                return CampaignDecision(
                    campaign_id=campaign_info.get('id', ''),
                    campaign_name=campaign_info.get('name', ''),
                    seller=campaign_info.get('seller', ''),
                    price_bucket=campaign_info.get('price_bucket', ''),
                    decision=DecisionType.PAUSE,
                    current_budget=current_budget,
                    reason=f"Poor ROAS ({roas:.2f}) and low recent traffic ({recent_impressions} impressions)",
                    confidence=0.8
                )
            else:
                new_budget = current_budget * self.rules.cut_factor
                new_troas = current_troas * self.rules.troas_increase_factor if current_troas > 0 else self.rules.target_roas
                return CampaignDecision(
                    campaign_id=campaign_info.get('id', ''),
                    campaign_name=campaign_info.get('name', ''),
                    seller=campaign_info.get('seller', ''),
                    price_bucket=campaign_info.get('price_bucket', ''),
                    decision=DecisionType.CUT,
                    current_budget=current_budget,
                    new_budget=new_budget,
                    current_troas=current_troas,
                    new_troas=new_troas,
                    reason=f"Poor ROAS ({roas:.2f}) - reducing budget and increasing tROAS",
                    confidence=0.7
                )
        
        elif roas >= self.rules.excellent_roas and impressions >= self.rules.high_volume_impressions:
            # Excellent performance with high volume - scale up
            new_budget = current_budget * self.rules.scale_factor
            new_troas = current_troas * self.rules.troas_decrease_factor if current_troas > 0 else self.rules.target_roas
            return CampaignDecision(
                campaign_id=campaign_info.get('id', ''),
                campaign_name=campaign_info.get('name', ''),
                seller=campaign_info.get('seller', ''),
                price_bucket=campaign_info.get('price_bucket', ''),
                decision=DecisionType.SCALE,
                current_budget=current_budget,
                new_budget=new_budget,
                current_troas=current_troas,
                new_troas=new_troas,
                reason=f"Excellent ROAS ({roas:.2f}) with high volume ({impressions} impressions) - scaling up",
                confidence=0.9
            )
        
        elif roas >= self.rules.target_roas and impressions >= self.rules.min_impressions:
            # Good performance - keep as is or slight optimization
            if current_troas > 0 and current_troas < roas * 0.8:
                # tROAS is too conservative, can be lowered
                new_troas = roas * 0.9
                return CampaignDecision(
                    campaign_id=campaign_info.get('id', ''),
                    campaign_name=campaign_info.get('name', ''),
                    seller=campaign_info.get('seller', ''),
                    price_bucket=campaign_info.get('price_bucket', ''),
                    decision=DecisionType.KEEP,
                    current_budget=current_budget,
                    new_budget=current_budget,
                    current_troas=current_troas,
                    new_troas=new_troas,
                    reason=f"Good ROAS ({roas:.2f}) - optimizing tROAS for better volume",
                    confidence=0.6
                )
            else:
                # Keep as is
                return CampaignDecision(
                    campaign_id=campaign_info.get('id', ''),
                    campaign_name=campaign_info.get('name', ''),
                    seller=campaign_info.get('seller', ''),
                    price_bucket=campaign_info.get('price_bucket', ''),
                    decision=DecisionType.KEEP,
                    current_budget=current_budget,
                    reason=f"Good performance (ROAS: {roas:.2f}) - keeping current settings",
                    confidence=0.5
                )
        
        # No decision for other cases
        return None
    
    def get_decision_summary(self, decisions: List[CampaignDecision]) -> Dict[str, int]:
        """Get summary of decisions made."""
        summary = {
            'total': len(decisions),
            'keep': 0,
            'scale': 0,
            'cut': 0,
            'pause': 0
        }
        
        for decision in decisions:
            summary[decision.decision.value] += 1
        
        return summary
    
    def filter_high_confidence_decisions(
        self, 
        decisions: List[CampaignDecision], 
        min_confidence: float = 0.7
    ) -> List[CampaignDecision]:
        """Filter decisions by confidence level."""
        return [d for d in decisions if d.confidence >= min_confidence]

def create_decision_rules_from_config(config: Dict[str, any]) -> DecisionRules:
    """Create DecisionRules from configuration dictionary."""
    return DecisionRules(
        min_roas=config.get('min_roas', 2.0),
        target_roas=config.get('target_roas', 4.0),
        excellent_roas=config.get('excellent_roas', 6.0),
        min_impressions=config.get('min_impressions', 1000),
        min_conversions=config.get('min_conversions', 5),
        high_volume_impressions=config.get('high_volume_impressions', 10000),
        scale_factor=config.get('scale_factor', 1.5),
        cut_factor=config.get('cut_factor', 0.7),
        troas_increase_factor=config.get('troas_increase_factor', 1.2),
        troas_decrease_factor=config.get('troas_decrease_factor', 0.9),
        min_days_data=config.get('min_days_data', 7),
        min_weekly_impressions=config.get('min_weekly_impressions', 500)
    )
