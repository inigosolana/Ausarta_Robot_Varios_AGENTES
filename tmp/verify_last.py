import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

# Check last campaign
camp = supabase.table("campaigns").select("*").order("created_at", desc=True).limit(1).execute()
print(f"Last Campaign: {camp.data}")

if camp.data:
    cid = camp.data[0]['id']
    leads = supabase.table("campaign_leads").select("*").eq("campaign_id", cid).execute()
    print(f"Leads for {cid}: {leads.data}")
