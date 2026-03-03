import os
from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

# 1) .env laden
load_dotenv()

# 2) Pad uit .env halen
cfg = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE")
print("GOOGLE_ADS_CONFIGURATION_FILE =", cfg)

try:
    # 3) Client laden vanaf dit pad
    client = GoogleAdsClient.load_from_storage(cfg)

    print("Effective login_customer_id =", getattr(client, "login_customer_id", None))

    # 4) Lijst toegankelijke klanten
    svc = client.get_service("CustomerService")
    res = svc.list_accessible_customers()
    print("\nAccessible customers for this refresh token:")
    for rn in res.resource_names:
        print(rn.split("/")[-1])

except FileNotFoundError:
    print("\n❌ Kon het YAML-bestand niet vinden.")
    print("Controleer of het pad klopt en bestaat:")
    print("  ", cfg)
    raise
except GoogleAdsException as ex:
    print("\n❌ Google Ads API error:", ex.error.code().name)
    for err in ex.failure.errors:
        print("-", err.error_code, err.message)
    raise
