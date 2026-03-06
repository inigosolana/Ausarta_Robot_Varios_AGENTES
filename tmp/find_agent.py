import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

res_agent = supabase.table("agent_config").select("id, name, empresa_id").limit(1).execute()
print(f"Agent: {res_agent.data}")
