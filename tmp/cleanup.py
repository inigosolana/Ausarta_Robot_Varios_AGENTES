import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

campaign_id = 16
print(f"[*] Limpiando datos de prueba para campaign_id {campaign_id}...")
supabase.table("campaign_leads").delete().eq("campaign_id", campaign_id).execute()
supabase.table("campaigns").delete().eq("id", campaign_id).execute()
print("[+] Limpieza completada.")
