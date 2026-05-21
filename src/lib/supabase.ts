import { createClient } from '@supabase/supabase-js';

const env = import.meta.env;
const supabaseUrl = env.VITE_SUPABASE_URL;
const supabaseAnonKey = env.VITE_SUPABASE_ANON_KEY || env.VITE_SUPABASE_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  console.error(
    '[Supabase] Defina VITE_SUPABASE_URL y VITE_SUPABASE_ANON_KEY en .env.local (ver .env.local.example).'
  );
}

/** Cliente único del frontend — todas las lecturas/escrituras van a Supabase (RLS). */
export const supabase = createClient(
  supabaseUrl || 'https://afrrxeibtrwjaiqmhytu.supabase.co',
  supabaseAnonKey || ''
);
