import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

res = supabase.table("campaigns").select("id, name, status").eq("status", "pending").execute()
print(f"Pending Campaigns: {res.data}")

if not res.data:
    res = supabase.table("campaigns").select("id, name, status").eq("status", "paused").execute()
    print(f"Paused Campaigns: {res.data}")

if res.data:
    campaign_id = res.data[0]['id']
    print(f"TARGET_CAMPAIGN_ID={campaign_id}")
else:
    print("NO_CAMPAIGN_FOUND")
