import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

# Check campaign
camp = supabase.table("campaigns").select("*").eq("id", 16).execute()
print(f"Campaign: {camp.data}")

# Check leads
leads = supabase.table("campaign_leads").select("*").eq("campaign_id", 16).execute()
print(f"Leads: {leads.data}")
