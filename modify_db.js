
import { createClient } from "@supabase/supabase-js";
const supabase = createClient("https://afrrxeibtrwjaiqmhytu.supabase.co", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFmcnJ4ZWlidHJ3amFpcW1oeXR1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE0MTA4NjAsImV4cCI6MjA4Njk4Njg2MH0.9k0C1EGjxAG47DJZx1jAweODFiaXenrjirYz91ZNpWs");
// Since we cant alter table via restful api normally, I will ask user to do it or I will try to use edge function / direct query, actually maybe I can just ask user to do it. But wait, I can modify the app to support the field.

