import os
from supabase import create_client
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

url = os.environ.get("SUPABASE_URL")
# Uso la service role key por que la anon key puede estar restringida por RLS para insert
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

# 1. Crear Campaña
camp_data = {
    "name": "TEST DRIP - Sofia (System)",
    "agent_id": 3,
    "empresa_id": 1,
    "status": "active",
    "interval_minutes": 1,
    "created_at": datetime.now(timezone.utc).isoformat()
}
res_camp = supabase.table("campaigns").insert(camp_data).execute()
campaign_id = res_camp.data[0]['id']
print(f"CREATED_CAMPAIGN_ID={campaign_id}")

# 2. Añadir un Lead de prueba
lead_data = {
    "campaign_id": campaign_id,
    "phone_number": "+34600000000",
    "customer_name": "Inigo Test",
    "status": "pending"
}
supabase.table("campaign_leads").insert(lead_data).execute()
print(f"CREATED_LEAD_FOR_CAMPAIGN={campaign_id}")
