/// <reference types="vite/client" />

interface ImportMetaEnv {
    readonly VITE_API_URL?: string
    /** IP pública del servidor Ausarta (whitelist en Yeastar P-Series) */
    readonly VITE_AUSARTA_PUBLIC_IP?: string
}

interface ImportMeta {
    readonly env: ImportMetaEnv
}
