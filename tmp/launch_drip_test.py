import asyncio
import os
import sys
from dotenv import load_dotenv

# Configurar encoding para evitar errores en Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Añadir el directorio actual al path para importar los routers
sys.path.append(os.getcwd())

from routers.campaigns import process_campaign_drip

async def main():
    load_dotenv()
    campaign_id = 16
    agent_id = 3
    interval = 1 # 1 minuto para el test
    
    print(f"[*] [Test Launch] Iniciando ejecucion directa de la campana {campaign_id}...")
    try:
        # Llamamos a la funcion asincrona que he refactored
        await process_campaign_drip(campaign_id, agent_id, interval)
        print("[+] Prueba de goteo finalizada.")
    except Exception as e:
        print(f"[-] Error en la ejecucion: {e}")

if __name__ == "__main__":
    asyncio.run(main())
