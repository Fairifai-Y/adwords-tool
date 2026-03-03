import os
from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient

# .env laden
load_dotenv()

cfg = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE")
print("Config path =", cfg)

# Client laden vanaf het expliciete pad
client = GoogleAdsClient.load_from_storage(cfg)

# --- jouw GAQL code hieronder ---
ga_service = client.get_service("GoogleAdsService")
query = """
    SELECT
      campaign.id,
      campaign.name
    FROM campaign
    LIMIT 10
"""
results = ga_service.search(
    customer_id="5059126003",  # of een andere toegankelijke klant-ID
    query=query
)
for row in results:
    print(f"Campaign {row.campaign.id} - {row.campaign.name}")
