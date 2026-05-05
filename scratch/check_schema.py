import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)

def get_columns(table):
    res = supabase.table(table).select("*").limit(1).execute()
    if res.data:
        print(f"Columns in {table}: {list(res.data[0].keys())}")
    else:
        print(f"No data in {table} to infer columns")

if __name__ == "__main__":
    get_columns("empresas")
    get_columns("company_yeastar_configs")
