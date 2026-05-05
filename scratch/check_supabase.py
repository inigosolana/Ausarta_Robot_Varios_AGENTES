import os
import requests
from dotenv import load_dotenv

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

def check_connection():
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}"
    }
    # Get table list from PostgREST openapi spec
    response = requests.get(f"{supabase_url}/rest/v1/?apikey={supabase_key}", headers=headers)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("Successfully connected to Supabase!")
        # Print tables if possible
        try:
            data = response.json()
            paths = data.get("paths", {})
            tables = [p for p in paths if p.startswith("/")]
            print(f"Found {len(tables)} tables/endpoints: {', '.join(tables[:10])}")
        except:
            print("Could not parse response JSON")
    else:
        print(f"Error: {response.text}")

if __name__ == "__main__":
    check_connection()

if __name__ == "__main__":
    check_connection()
