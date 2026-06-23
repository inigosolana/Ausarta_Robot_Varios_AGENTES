/// <reference types="vite/client" />

interface ImportMetaEnv {
    readonly VITE_API_URL?: string
    readonly VITE_LIVEKIT_URL?: string
    readonly VITE_SUPABASE_URL?: string
    readonly VITE_SUPABASE_ANON_KEY?: string
    /** IP pública del servidor Ausarta (whitelist en Yeastar P-Series) */
    readonly VITE_AUSARTA_PUBLIC_IP?: string
}

interface ImportMeta {
    readonly env: ImportMetaEnv
}
