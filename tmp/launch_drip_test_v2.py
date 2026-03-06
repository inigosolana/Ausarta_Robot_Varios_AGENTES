import asyncio
import os
import sys
from dotenv import load_dotenv

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.append(os.getcwd())

from routers.campaigns import process_campaign_drip

async def main():
    load_dotenv()
    # Usar el ID dinámico si es posible, o el último creado
    from supabase import create_client
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    res = supabase.table("campaigns").select("id, agent_id").order("created_at", desc=True).limit(1).execute()
    if not res.data:
        print("[-] No se encontró campaña.")
        return
        
    campaign_id = res.data[0]['id']
    agent_id = res.data[0]['agent_id']
    interval = 1 
    
    print(f"[*] [Test Launch] Iniciando ejecucion directa de la campana {campaign_id} (Agent {agent_id})...")
    try:
        await process_campaign_drip(campaign_id, agent_id, interval)
        print("[+] Prueba de goteo finalizada.")
    except Exception as e:
        print(f"[-] Error en la ejecucion: {e}")

if __name__ == "__main__":
    asyncio.run(main())
