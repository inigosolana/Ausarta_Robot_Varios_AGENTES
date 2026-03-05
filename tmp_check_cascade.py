import os
from supabase import create_client

SUPABASE_URL = "https://afrrxeibtrwjaiqmhytu.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFmcnJ4ZWlidHJ3amFpcW1oeXR1Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTQxMDg2MCwiZXhwIjoyMDg2OTg2ODYwfQ.hbjkzKxk1MnKn3otvrdp9yJpjUklYbT5sr_L1Gs6nXg"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def check_dependencies(agent_id):
    print(f"Checking dependencies for Agent ID: {agent_id}")
    
    # Check ai_config
    ai = supabase.table("ai_config").select("id").eq("agent_id", agent_id).execute()
    print(f"ai_config: {len(ai.data)} records")

    # Check encuestas
    enc = supabase.table("encuestas").select("id").eq("agent_id", agent_id).execute()
    print(f"encuestas: {len(enc.data)} records")

    # Check campaigns
    camp = supabase.table("campaigns").select("id").eq("agent_id", agent_id).execute()
    print(f"campaigns: {len(camp.data)} records")
    
    if camp.data:
        for c in camp.data:
            leads = supabase.table("campaign_leads").select("id").eq("campaign_id", c['id']).execute()
            print(f"  -> Campaign {c['id']} has {len(leads.data)} leads")

if __name__ == "__main__":
    # Check for Kerman (ID 4) as an example
    check_dependencies(4)
