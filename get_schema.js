
import { createClient } from "@supabase/supabase-js";
const supabase = createClient("https://afrrxeibtrwjaiqmhytu.supabase.co", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFmcnJ4ZWlidHJ3amFpcW1oeXR1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE0MTA4NjAsImV4cCI6MjA4Njk4Njg2MH0.9k0C1EGjxAG47DJZx1jAweODFiaXenrjirYz91ZNpWs");
async function run() {
  const { data: pData } = await supabase.from("user_profiles").select("*").limit(1);
  console.log("user_profiles:", pData);
  const { data: aData } = await supabase.from("agent_config").select("*").limit(1);
  console.log("agent_config:", aData);
}
run();

