import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

res = supabase.table("encuestas").select("campaign_id").order("id", desc=True).limit(5).execute()
print(f"Recent Surveys with Campaign IDs: {res.data}")
