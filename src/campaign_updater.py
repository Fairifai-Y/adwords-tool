"""Campaign update functionality for automated campaign management.

This module handles updating existing campaigns based on decisions from the decision engine.
"""

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.protobuf import field_mask_pb2

from decision_engine import CampaignDecision, DecisionType

logger = logging.getLogger(__name__)

@dataclass
class UpdateResult:
    """Result of a campaign update operation."""
    campaign_id: str
    success: bool
    error_message: Optional[str] = None
    changes_applied: List[str] = None

class CampaignUpdater:
    """Handles updating campaigns based on decisions."""
    
    def __init__(self, client: GoogleAdsClient):
        """Initialize campaign updater with Google Ads client."""
        self.client = client
    
    def apply_decisions(self, decisions: List[CampaignDecision], customer_id: str) -> List[UpdateResult]:
        """
        Apply campaign decisions to Google Ads.
        
        Args:
            decisions: List of campaign decisions to apply
            customer_id: Google Ads customer ID
            
        Returns:
            List of update results
        """
        results = []
        
        for decision in decisions:
            try:
                result = self._apply_decision(decision, customer_id)
                results.append(result)
                
                # Small delay to avoid rate limiting
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error applying decision for campaign {decision.campaign_id}: {e}")
                results.append(UpdateResult(
                    campaign_id=decision.campaign_id,
                    success=False,
                    error_message=str(e)
                ))
        
        return results
    
    def _apply_decision(self, decision: CampaignDecision, customer_id: str) -> UpdateResult:
        """Apply a single campaign decision."""
        changes_applied = []
        
        try:
            # Update budget if needed
            if decision.new_budget and decision.new_budget != decision.current_budget:
                self._update_campaign_budget(decision, customer_id)
                changes_applied.append(f"Budget: {decision.current_budget} -> {decision.new_budget}")
            
            # Update tROAS if needed
            if decision.new_troas and decision.new_troas != decision.current_troas:
                self._update_campaign_troas(decision, customer_id)
                changes_applied.append(f"tROAS: {decision.current_troas} -> {decision.new_troas}")
            
            # Pause campaign if needed
            if decision.decision == DecisionType.PAUSE:
                self._pause_campaign(decision, customer_id)
                changes_applied.append("Campaign paused")
            
            return UpdateResult(
                campaign_id=decision.campaign_id,
                success=True,
                changes_applied=changes_applied
            )
            
        except Exception as e:
            return UpdateResult(
                campaign_id=decision.campaign_id,
                success=False,
                error_message=str(e)
            )
    
    def _update_campaign_budget(self, decision: CampaignDecision, customer_id: str):
        """Update campaign budget."""
        # First, get the campaign to find its budget
        campaign_info = self._get_campaign_info(decision.campaign_id, customer_id)
        if not campaign_info or 'budget_id' not in campaign_info:
            raise Exception(f"Could not find budget for campaign {decision.campaign_id}")
        
        budget_id = campaign_info['budget_id']
        
        # Update the budget
        budget_service = self.client.get_service("CampaignBudgetService")
        budget_operation = self.client.get_type("CampaignBudgetOperation")
        budget = budget_operation.update
        budget.resource_name = budget_id
        budget.amount_micros = int(decision.new_budget * 1_000_000)  # Convert to micros
        
        budget_operation.update_mask.CopyFrom(
            field_mask_pb2.FieldMask(paths=["amount_micros"])
        )
        
        budget_service.mutate_campaign_budgets(
            customer_id=customer_id, 
            operations=[budget_operation]
        )
        
        logger.info(f"Updated budget for campaign {decision.campaign_id} to {decision.new_budget}")
    
    def _update_campaign_troas(self, decision: CampaignDecision, customer_id: str):
        """Update campaign tROAS."""
        campaign_service = self.client.get_service("CampaignService")
        campaign_operation = self.client.get_type("CampaignOperation")
        campaign = campaign_operation.update
        campaign.resource_name = decision.campaign_id
        campaign.maximize_conversion_value.target_roas = decision.new_troas
        
        campaign_operation.update_mask.CopyFrom(
            field_mask_pb2.FieldMask(paths=["maximize_conversion_value.target_roas"])
        )
        
        campaign_service.mutate_campaigns(
            customer_id=customer_id,
            operations=[campaign_operation]
        )
        
        logger.info(f"Updated tROAS for campaign {decision.campaign_id} to {decision.new_troas}")
    
    def _pause_campaign(self, decision: CampaignDecision, customer_id: str):
        """Pause a campaign."""
        campaign_service = self.client.get_service("CampaignService")
        campaign_operation = self.client.get_type("CampaignOperation")
        campaign = campaign_operation.update
        campaign.resource_name = decision.campaign_id
        campaign.status = self.client.enums.CampaignStatusEnum.PAUSED
        
        campaign_operation.update_mask.CopyFrom(
            field_mask_pb2.FieldMask(paths=["status"])
        )
        
        campaign_service.mutate_campaigns(
            customer_id=customer_id,
            operations=[campaign_operation]
        )
        
        logger.info(f"Paused campaign {decision.campaign_id}")
    
    def _get_campaign_info(self, campaign_id: str, customer_id: str) -> Optional[Dict[str, Any]]:
        """Get campaign information including budget ID."""
        ga_service = self.client.get_service("GoogleAdsService")
        
        query = f"""
        SELECT 
            campaign.resource_name,
            campaign.name,
            campaign.campaign_budget,
            campaign.maximize_conversion_value.target_roas,
            campaign.status
        FROM campaign 
        WHERE campaign.resource_name = '{campaign_id}'
        """
        
        try:
            for row in ga_service.search(customer_id=customer_id, query=query):
                return {
                    'id': row.campaign.resource_name,
                    'name': row.campaign.name,
                    'budget_id': row.campaign.campaign_budget,
                    'troas': row.campaign.maximize_conversion_value.target_roas if row.campaign.maximize_conversion_value else None,
                    'status': row.campaign.status.name
                }
        except Exception as e:
            logger.error(f"Error getting campaign info for {campaign_id}: {e}")
        
        return None
    
    def get_campaign_performance(self, customer_id: str, days_back: int = 30) -> Dict[str, Dict]:
        """Get current campaign performance data."""
        ga_service = self.client.get_service("GoogleAdsService")
        
        query = f"""
        SELECT 
            campaign.resource_name,
            campaign.name,
            campaign.status,
            campaign.campaign_budget,
            campaign.maximize_conversion_value.target_roas,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.conversions_value,
            metrics.cost_micros
        FROM campaign 
        WHERE segments.date DURING LAST_{days_back}_DAYS
        AND campaign.advertising_channel_type = 'PERFORMANCE_MAX'
        AND campaign.status IN ('ENABLED', 'PAUSED')
        """
        
        campaigns = {}
        
        try:
            for row in ga_service.search(customer_id=customer_id, query=query):
                campaign_id = row.campaign.resource_name
                
                # Get budget amount
                budget_amount = self._get_budget_amount(row.campaign.campaign_budget, customer_id)
                
                campaigns[campaign_id] = {
                    'id': campaign_id,
                    'name': row.campaign.name,
                    'status': row.campaign.status.name,
                    'budget': budget_amount,
                    'troas': row.campaign.maximize_conversion_value.target_roas if row.campaign.maximize_conversion_value else None,
                    'impressions': row.metrics.impressions,
                    'clicks': row.metrics.clicks,
                    'conversions': row.metrics.conversions,
                    'conversions_value': row.metrics.conversions_value,
                    'cost': row.metrics.cost_micros / 1_000_000,
                    'roas': row.metrics.conversions_value / (row.metrics.cost_micros / 1_000_000) if row.metrics.cost_micros > 0 else 0
                }
        except Exception as e:
            logger.error(f"Error getting campaign performance: {e}")
        
        return campaigns
    
    def _get_budget_amount(self, budget_resource_name: str, customer_id: str) -> float:
        """Get budget amount from budget resource name."""
        ga_service = self.client.get_service("GoogleAdsService")
        
        query = f"""
        SELECT campaign_budget.amount_micros
        FROM campaign_budget 
        WHERE campaign_budget.resource_name = '{budget_resource_name}'
        """
        
        try:
            for row in ga_service.search(customer_id=customer_id, query=query):
                return row.campaign_budget.amount_micros / 1_000_000
        except Exception as e:
            logger.error(f"Error getting budget amount for {budget_resource_name}: {e}")
        
        return 0.0

def create_campaign_updater(client: GoogleAdsClient) -> CampaignUpdater:
    """Create a campaign updater instance."""
    return CampaignUpdater(client)











