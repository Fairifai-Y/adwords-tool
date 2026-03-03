"""Database models and connection for automated campaign management.

This module provides PostgreSQL database functionality for storing and retrieving
label performance data, campaign decisions, and historical trends.
"""

import os
import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql
import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class LabelPerformanceData:
    """Data structure for label performance metrics."""
    date: date
    seller: str
    country: str
    price_bucket: str
    product_type: str
    impressions: int
    clicks: int
    conversions: int
    value: float
    cost: float
    roas: float
    cpa: float
    roi: float
    ctr: float
    conversion_rate: float
    avg_cpc: float

class DatabaseManager:
    """Manages PostgreSQL database connections and operations."""
    
    def __init__(self, connection_string: Optional[str] = None):
        """Initialize database manager with connection string."""
        # Load .env file
        from dotenv import load_dotenv
        load_dotenv()
        
        self.connection_string = connection_string or self._get_connection_string()
        self._ensure_tables_exist()
    
    def _get_connection_string(self) -> str:
        """Get database connection string from environment or config."""
        # Try environment variables first
        if db_url := os.getenv('DATABASE_URL'):
            return db_url
        
        # Try individual components
        host = os.getenv('DB_HOST', 'localhost')
        port = os.getenv('DB_PORT', '5432')
        database = os.getenv('DB_NAME', 'adwords_automation')
        user = os.getenv('DB_USER', 'postgres')
        password = os.getenv('DB_PASSWORD', '')
        
        return f"postgresql://{user}:{password}@{host}:{port}/{database}"
    
    def _ensure_tables_exist(self):
        """Create database tables if they don't exist."""
        create_tables_sql = """
        -- Label performance data table
        CREATE TABLE IF NOT EXISTS label_performance (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            seller VARCHAR(255) NOT NULL,
            country VARCHAR(10) NOT NULL,
            price_bucket VARCHAR(50) NOT NULL,
            product_type VARCHAR(100) NOT NULL,
            impressions INTEGER NOT NULL DEFAULT 0,
            clicks INTEGER NOT NULL DEFAULT 0,
            conversions INTEGER NOT NULL DEFAULT 0,
            value DECIMAL(10,2) NOT NULL DEFAULT 0.0,
            cost DECIMAL(10,2) NOT NULL DEFAULT 0.0,
            roas DECIMAL(8,4) NOT NULL DEFAULT 0.0,
            cpa DECIMAL(8,2) NOT NULL DEFAULT 0.0,
            roi DECIMAL(8,4) NOT NULL DEFAULT 0.0,
            ctr DECIMAL(8,4) NOT NULL DEFAULT 0.0,
            conversion_rate DECIMAL(8,4) NOT NULL DEFAULT 0.0,
            avg_cpc DECIMAL(8,2) NOT NULL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, seller, country, price_bucket, product_type)
        );
        
        -- Campaign decisions table
        CREATE TABLE IF NOT EXISTS campaign_decisions (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            campaign_id VARCHAR(255) NOT NULL,
            campaign_name VARCHAR(500) NOT NULL,
            seller VARCHAR(255) NOT NULL,
            price_bucket VARCHAR(50) NOT NULL,
            decision VARCHAR(50) NOT NULL, -- 'keep', 'scale', 'cut', 'pause'
            current_budget DECIMAL(10,2),
            new_budget DECIMAL(10,2),
            current_troas DECIMAL(8,4),
            new_troas DECIMAL(8,4),
            reason TEXT,
            applied BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Campaign performance history
        CREATE TABLE IF NOT EXISTS campaign_performance_history (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            campaign_id VARCHAR(255) NOT NULL,
            campaign_name VARCHAR(500) NOT NULL,
            seller VARCHAR(255) NOT NULL,
            price_bucket VARCHAR(50) NOT NULL,
            impressions INTEGER NOT NULL DEFAULT 0,
            clicks INTEGER NOT NULL DEFAULT 0,
            conversions INTEGER NOT NULL DEFAULT 0,
            value DECIMAL(10,2) NOT NULL DEFAULT 0.0,
            cost DECIMAL(10,2) NOT NULL DEFAULT 0.0,
            budget DECIMAL(10,2) NOT NULL DEFAULT 0.0,
            troas DECIMAL(8,4) NOT NULL DEFAULT 0.0,
            status VARCHAR(50) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Indexes for better performance
        CREATE INDEX IF NOT EXISTS idx_label_performance_date ON label_performance(date);
        CREATE INDEX IF NOT EXISTS idx_label_performance_seller ON label_performance(seller);
        CREATE INDEX IF NOT EXISTS idx_label_performance_seller_date ON label_performance(seller, date);
        CREATE INDEX IF NOT EXISTS idx_campaign_decisions_date ON campaign_decisions(date);
        CREATE INDEX IF NOT EXISTS idx_campaign_decisions_seller ON campaign_decisions(seller);
        CREATE INDEX IF NOT EXISTS idx_campaign_performance_date ON campaign_performance_history(date);
        CREATE INDEX IF NOT EXISTS idx_campaign_performance_seller ON campaign_performance_history(seller);
        """
        
        try:
            with psycopg2.connect(self.connection_string) as conn:
                with conn.cursor() as cur:
                    cur.execute(create_tables_sql)
                    conn.commit()
            logger.info("Database tables created/verified successfully")
        except Exception as e:
            logger.error(f"Error creating database tables: {e}")
            raise
    
    def save_label_data(self, data: List[LabelPerformanceData]) -> bool:
        """Save label performance data to database."""
        if not data:
            return True
        
        insert_sql = """
        INSERT INTO label_performance 
        (date, seller, country, price_bucket, product_type, impressions, clicks, 
         conversions, value, cost, roas, cpa, roi, ctr, conversion_rate, avg_cpc)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (date, seller, country, price_bucket, product_type) 
        DO UPDATE SET
            impressions = EXCLUDED.impressions,
            clicks = EXCLUDED.clicks,
            conversions = EXCLUDED.conversions,
            value = EXCLUDED.value,
            cost = EXCLUDED.cost,
            roas = EXCLUDED.roas,
            cpa = EXCLUDED.cpa,
            roi = EXCLUDED.roi,
            ctr = EXCLUDED.ctr,
            conversion_rate = EXCLUDED.conversion_rate,
            avg_cpc = EXCLUDED.avg_cpc,
            created_at = CURRENT_TIMESTAMP
        """
        
        try:
            with psycopg2.connect(self.connection_string) as conn:
                with conn.cursor() as cur:
                    for record in data:
                        cur.execute(insert_sql, (
                            record.date, record.seller, record.country, record.price_bucket,
                            record.product_type, record.impressions, record.clicks,
                            record.conversions, record.value, record.cost,
                            record.roas, record.cpa, record.roi, record.ctr,
                            record.conversion_rate, record.avg_cpc
                        ))
                    conn.commit()
            logger.info(f"Saved {len(data)} label performance records")
            return True
        except Exception as e:
            logger.error(f"Error saving label data: {e}")
            return False
    
    def get_seller_performance(self, seller: str, days: int = 30) -> pd.DataFrame:
        """Get performance data for a specific seller."""
        query = """
        SELECT * FROM label_performance 
        WHERE seller = %s AND date >= %s
        ORDER BY date DESC
        """
        
        try:
            with psycopg2.connect(self.connection_string) as conn:
                return pd.read_sql_query(
                    query, 
                    conn, 
                    params=[seller, date.today().replace(day=1) if days == 30 else date.today().replace(day=1)],
                    parse_dates=['date']
                )
        except Exception as e:
            logger.error(f"Error getting seller performance: {e}")
            return pd.DataFrame()
    
    def get_weekly_trends(self, weeks: int = 4) -> pd.DataFrame:
        """Get weekly performance trends for all sellers."""
        query = """
        SELECT 
            seller,
            price_bucket,
            DATE_TRUNC('week', date) as week,
            SUM(impressions) as total_impressions,
            SUM(clicks) as total_clicks,
            SUM(conversions) as total_conversions,
            SUM(value) as total_value,
            SUM(cost) as total_cost,
            AVG(roas) as avg_roas,
            AVG(ctr) as avg_ctr,
            AVG(conversion_rate) as avg_conversion_rate
        FROM label_performance 
        WHERE date >= %s
        GROUP BY seller, price_bucket, DATE_TRUNC('week', date)
        ORDER BY week DESC, total_value DESC
        """
        
        try:
            with psycopg2.connect(self.connection_string) as conn:
                return pd.read_sql_query(
                    query, 
                    conn, 
                    params=[date.today().replace(day=1)],
                    parse_dates=['week']
                )
        except Exception as e:
            logger.error(f"Error getting weekly trends: {e}")
            return pd.DataFrame()
    
    def save_campaign_decision(self, decision: Dict[str, Any]) -> bool:
        """Save a campaign decision to the database."""
        insert_sql = """
        INSERT INTO campaign_decisions 
        (date, campaign_id, campaign_name, seller, price_bucket, decision, 
         current_budget, new_budget, current_troas, new_troas, reason, applied)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        try:
            with psycopg2.connect(self.connection_string) as conn:
                with conn.cursor() as cur:
                    cur.execute(insert_sql, (
                        decision.get('date', date.today()),
                        decision.get('campaign_id', ''),
                        decision.get('campaign_name', ''),
                        decision.get('seller', ''),
                        decision.get('price_bucket', ''),
                        decision.get('decision', 'keep'),
                        decision.get('current_budget'),
                        decision.get('new_budget'),
                        decision.get('current_troas'),
                        decision.get('new_troas'),
                        decision.get('reason', ''),
                        decision.get('applied', False)
                    ))
                    conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving campaign decision: {e}")
            return False
    
    def get_pending_decisions(self) -> List[Dict[str, Any]]:
        """Get all pending campaign decisions that haven't been applied."""
        query = """
        SELECT * FROM campaign_decisions 
        WHERE applied = FALSE
        ORDER BY date DESC, seller, price_bucket
        """
        
        try:
            with psycopg2.connect(self.connection_string, cursor_factory=RealDictCursor) as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"Error getting pending decisions: {e}")
            return []
    
    def mark_decision_applied(self, decision_id: int) -> bool:
        """Mark a campaign decision as applied."""
        update_sql = "UPDATE campaign_decisions SET applied = TRUE WHERE id = %s"
        
        try:
            with psycopg2.connect(self.connection_string) as conn:
                with conn.cursor() as cur:
                    cur.execute(update_sql, (decision_id,))
                    conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error marking decision as applied: {e}")
            return False

def convert_labels_to_performance_data(
    labels: Dict[str, Dict], 
    label_index: int,
    country: str = "NL",
    product_type: str = "ALL"
) -> List[LabelPerformanceData]:
    """Convert discovered labels to LabelPerformanceData format."""
    performance_data = []
    today = date.today()
    
    for label, data in labels.items():
        # Extract price bucket from custom_label_2 if available
        price_bucket = "UNKNOWN"
        if 'custom_label_2' in data and data['custom_label_2']:
            price_bucket = list(data['custom_label_2'])[0] if data['custom_label_2'] else "UNKNOWN"
        
        performance_data.append(LabelPerformanceData(
            date=today,
            seller=label,
            country=country,
            price_bucket=price_bucket,
            product_type=product_type,
            impressions=data.get('impressions', 0),
            clicks=data.get('clicks', 0),
            conversions=data.get('conversions', 0),
            value=data.get('conversions_value', 0.0),
            cost=data.get('cost', 0.0),
            roas=data.get('roas', 0.0),
            cpa=data.get('cpa', 0.0),
            roi=data.get('roi', 0.0),
            ctr=data.get('ctr', 0.0),
            conversion_rate=data.get('conversion_rate', 0.0),
            avg_cpc=data.get('avg_cpc', 0.0)
        ))
    
    return performance_data
