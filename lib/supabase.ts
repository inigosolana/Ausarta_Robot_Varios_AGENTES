import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || 'https://afrrxeibtrwjaiqmhytu.supabase.co';
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || import.meta.env.VITE_SUPABASE_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFmcnJ4ZWlidHJ3amFpcW1oeXR1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE0MTA4NjAsImV4cCI6MjA4Njk4Njg2MH0.9k0C1EGjxAG47DJZx1jAweODFiaXenrjirYz91ZNpWs';

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
