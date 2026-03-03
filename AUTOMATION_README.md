# Automated Campaign Management System

Dit is een uitgebreide versie van het originele `label_campaigns.py` script met volledige automatisering voor campagnebeheer.

## 🚀 Nieuwe Functionaliteiten

### 1. **PostgreSQL Database Opslag**
- Dagelijkse opslag van performance data per seller/price bucket
- Historische trendanalyse mogelijk
- Campaign decision tracking

### 2. **Automatische Decision Rules**
- **Bleeders**: ROAS < 2.0 → budget verlagen of pauzeren
- **Toppers**: ROAS > 6.0 + hoog volume → budget verhogen
- **Optimizers**: ROAS 2.0-6.0 → tROAS optimaliseren

### 3. **Segmentatie per Seller × Price Bucket**
- Aparte campagnes per seller en prijsbucket
- Automatische campagne creatie voor nieuwe sellers
- Flexibele targeting per segment

### 4. **Automatisering**
- Dagelijkse data collectie en opslag
- Wekelijkse decision making en updates
- Cron job / Task Scheduler support

## 📁 Bestandsstructuur

```
src/
├── automated_campaign_manager.py  # Hoofdscript (nieuw)
├── database.py                    # PostgreSQL functionaliteit (nieuw)
├── decision_engine.py             # Decision rules engine (nieuw)
├── campaign_updater.py            # Campaign update functionaliteit (nieuw)
├── scheduler.py                   # Automatisering scheduler (nieuw)
├── label_campaigns.py             # Origineel script (ongewijzigd)
└── weekly_campaign_monitor.py     # Bestaand script (ongewijzigd)

config/
├── automation_config.json         # Configuratie (nieuw)
└── google-ads.yaml               # Bestaande Google Ads config

requirements.txt                   # Updated met nieuwe dependencies
```

## 🛠️ Installatie

### 1. Dependencies Installeren
```bash
pip install -r requirements.txt
```

### 2. PostgreSQL Database Setup
```sql
-- Maak database aan
CREATE DATABASE adwords_automation;

-- Maak gebruiker aan (optioneel)
CREATE USER adwords_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE adwords_automation TO adwords_user;
```

### 3. Environment Variables
```bash
# Database connectie
export DATABASE_URL="postgresql://user:password@localhost:5432/adwords_automation"

# Of individuele componenten
export DB_HOST="localhost"
export DB_PORT="5432"
export DB_NAME="adwords_automation"
export DB_USER="postgres"
export DB_PASSWORD="your_password"

# Google Ads (bestaand)
export GOOGLE_ADS_CONFIGURATION_FILE="config/google-ads.yaml"
```

## 🚀 Gebruik

### 1. Dagelijkse Analyse (Dry Run)
```bash
python src/automated_campaign_manager.py --customer 5059126003 --mode daily
```

### 2. Dagelijkse Analyse (Met Toepassing)
```bash
python src/automated_campaign_manager.py --customer 5059126003 --mode daily --apply
```

### 3. Wekelijkse Analyse
```bash
python src/automated_campaign_manager.py --customer 5059126003 --mode weekly --apply
```

### 4. Met Configuratiebestand
```bash
python src/automated_campaign_manager.py --customer 5059126003 --mode daily --config config/automation_config.json --apply
```

## ⚙️ Configuratie

### Decision Rules Aanpassen
Bewerk `config/automation_config.json`:

```json
{
  "decision_rules": {
    "min_roas": 2.0,           // Minimum ROAS voor actieve campagnes
    "target_roas": 4.0,        // Doel ROAS
    "excellent_roas": 6.0,     // Uitstekende ROAS (scale up)
    "min_impressions": 1000,   // Minimum impressies voor beslissing
    "scale_factor": 1.5,       // Budget verhoging factor
    "cut_factor": 0.7          // Budget verlaging factor
  }
}
```

## 🤖 Automatisering

### 1. Linux/Mac (Cron)
```bash
# Dagelijks om 9:00
0 9 * * * /path/to/python /path/to/src/scheduler.py --customer 5059126003 --mode daily

# Wekelijks op maandag om 10:00
0 10 * * 1 /path/to/python /path/to/src/scheduler.py --customer 5059126003 --mode weekly
```

### 2. Windows (Task Scheduler)
1. Open Task Scheduler
2. Create Basic Task
3. Trigger: Daily/Weekly
4. Action: Start a program
5. Program: `python.exe`
6. Arguments: `src/scheduler.py --customer 5059126003 --mode daily`

## 📊 Database Schema

### label_performance
```sql
CREATE TABLE label_performance (
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
```

### campaign_decisions
```sql
CREATE TABLE campaign_decisions (
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
```

## 📈 Rapporten

### 1. Wekelijkse CSV Export
Automatisch gegenereerd in project root:
- `weekly_report_YYYYMMDD.csv`

### 2. Console Output
```
WEEKLY PERFORMANCE SUMMARY
============================================================

TOP 10 PERFORMERS (by value):
  seller1 (50-100): €1,234.56 | ROAS: 5.67 | Impressions: 12,345
  seller2 (100-200): €987.65 | ROAS: 4.23 | Impressions: 8,765

UNDERPERFORMERS (ROAS < 2.0):
  seller3 (<50): ROAS: 1.45 | Impressions: 2,345
  seller4 (200+): ROAS: 1.78 | Impressions: 1,234
```

## 🔧 Uitbreidbaarheid

### 1. Nieuwe Platforms Toevoegen
Het systeem is ontworpen om uit te breiden naar andere platforms:

```python
# Voor Meta/TikTok API's
class MetaCampaignUpdater(CampaignUpdater):
    def apply_decisions(self, decisions, account_id):
        # Meta API implementatie
        pass

class TikTokCampaignUpdater(CampaignUpdater):
    def apply_decisions(self, decisions, account_id):
        # TikTok API implementatie
        pass
```

### 2. Nieuwe Decision Rules
```python
# Aangepaste decision rules
custom_rules = DecisionRules(
    min_roas=1.5,           # Lagere drempel
    target_roas=3.0,        # Conservatiever doel
    excellent_roas=5.0,     # Lagere excellent drempel
    scale_factor=2.0,       # Agressievere scaling
    cut_factor=0.5          # Agressievere cutting
)
```

## 🚨 Troubleshooting

### 1. Database Connectie Problemen
```bash
# Test database connectie
python -c "from src.database import DatabaseManager; db = DatabaseManager(); print('Connected!')"
```

### 2. Google Ads API Problemen
```bash
# Test Google Ads connectie
python -c "from google.ads.googleads.client import GoogleAdsClient; client = GoogleAdsClient.load_from_storage('config/google-ads.yaml'); print('Connected!')"
```

### 3. Logs Bekijken
```bash
# Bekijk automation logs
tail -f automation.log
```

## 📝 Migratie van Origineel Script

Het originele `label_campaigns.py` script blijft volledig functioneel. De nieuwe functionaliteit is een uitbreiding:

1. **Origineel script**: Handmatige campagne creatie
2. **Nieuw script**: Volledige automatisering + originele functionaliteit

Je kunt beide naast elkaar gebruiken:
- `label_campaigns.py` voor handmatige acties
- `automated_campaign_manager.py` voor dagelijkse automatisering

## 🎯 Volgende Stappen

1. **Test de setup** met `--mode daily` (dry run)
2. **Configureer decision rules** in `automation_config.json`
3. **Setup automatisering** met cron/Task Scheduler
4. **Monitor logs** en pas regels aan
5. **Uitbreiden** naar andere platforms indien gewenst

## 📞 Support

Voor vragen of problemen:
1. Check de logs in `automation.log`
2. Test database connectie
3. Test Google Ads API connectie
4. Controleer configuratiebestanden











