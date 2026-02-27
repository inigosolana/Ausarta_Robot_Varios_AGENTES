import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

const resources = {
    es: {
        translation: {
            "Dashboard": "Panel de Control",
            "Campaigns": "Campañas",
            "Agents": "Agentes",
            "Results": "Resultados",
            "Settings": "Ajustes",
            "Test Call": "Prueba de Llamada",
            "Logout": "Cerrar sesión",
            "Survey Results": "Resultados de Encuestas",
            "Detailed view of all agent interactions": "Vista detallada de todas las interacciones de los agentes",
            "Todas las empresas": "Todas las empresas",
            "Search by phone, comments or transcript...": "Buscar por teléfono, comentarios o transcripción...",
            "ID": "ID",
            "Phone / Campaign": "Teléfono / Campaña",
            "Date": "Fecha",
            "Status": "Estado",
            "Results / Scores": "Resultados / Puntos",
            "Model": "Modelo",
            "Comments": "Comentarios",
            "More": "Más",
            "No results found": "No se encontraron resultados",
            "Completa": "Completa",
            "Incompleta": "Incompleta",
            "Rechazada": "Rechazada",
            "Fallida": "Fallida",
            "No Contesta": "No Contesta",
            "Pendiente": "Pendiente",
            "Preguntas Abiertas": "Preguntas Abiertas",
            "None": "Ninguno",
            "Retry": "Reintentar",
            "Transcript": "Transcripción",
            "Export CSV": "Exportar CSV"
        }
    },
    en: {
        translation: {
            "Dashboard": "Dashboard",
            "Campaigns": "Campaigns",
            "Agents": "Agents",
            "Results": "Results",
            "Settings": "Settings",
            "Test Call": "Test Call",
            "Logout": "Logout",
            "Survey Results": "Survey Results",
            "Detailed view of all agent interactions": "Detailed view of all agent interactions",
            "Todas las empresas": "All companies",
            "Search by phone, comments or transcript...": "Search by phone, comments or transcript...",
            "ID": "ID",
            "Phone / Campaign": "Phone / Campaign",
            "Date": "Date",
            "Status": "Status",
            "Results / Scores": "Results / Scores",
            "Model": "Model",
            "Comments": "Comments",
            "More": "More",
            "No results found": "No results found",
            "Completa": "Completed",
            "Incompleta": "Incomplete",
            "Rechazada": "Rejected",
            "Fallida": "Failed",
            "No Contesta": "No Answer",
            "Pendiente": "Pending",
            "Preguntas Abiertas": "Open Questions",
            "None": "None",
            "Retry": "Retry",
            "Transcript": "Transcript",
            "Export CSV": "Export CSV"
        }
    },
    eu: {
        translation: {
            "Dashboard": "Aginte-Panela",
            "Campaigns": "Kanpainak",
            "Agents": "Agenteak",
            "Results": "Emaitzak",
            "Settings": "Ezarpenak",
            "Test Call": "Dei Proba",
            "Logout": "Saioa amaitu",
            "Survey Results": "Inkesten Emaitzak",
            "Detailed view of all agent interactions": "Agenteen elkarreragin guztien ikuspegi zehatza",
            "Todas las empresas": "Enpresa guztiak",
            "Search by phone, comments or transcript...": "Bilatu telefono, iruzkin edo transkripzioz...",
            "ID": "IDa",
            "Phone / Campaign": "Telefonoa / Kanpaina",
            "Date": "Data",
            "Status": "Egoera",
            "Results / Scores": "Emaitzak / Puntuazioak",
            "Model": "Eredua",
            "Comments": "Iruzkinak",
            "More": "Gehiago",
            "No results found": "Ez da emaitzarik aurkitu",
            "Completa": "Osatua",
            "Incompleta": "Osatugabea",
            "Rechazada": "Baztertua",
            "Fallida": "Huts egina",
            "No Contesta": "Ez du erantzuten",
            "Pendiente": "Egiteke",
            "Preguntas Abiertas": "Galdera Irekiak",
            "None": "Bat ere ez",
            "Retry": "Berrabiarazi",
            "Transcript": "Transkripzioa",
            "Export CSV": "Esportatu CSV"
        }
    },
    gl: {
        translation: {
            "Dashboard": "Panel de Control",
            "Campaigns": "Campañas",
            "Agents": "Axentes",
            "Results": "Resultados",
            "Settings": "Axustes",
            "Test Call": "Proba de Chamada",
            "Logout": "Pechar sesión",
            "Survey Results": "Resultados de Enquisas",
            "Detailed view of all agent interactions": "Vista detallada de todas as interaccións dos axentes",
            "Todas las empresas": "Todas as empresas",
            "Search by phone, comments or transcript...": "Buscar por teléfono, comentarios ou transcrición...",
            "ID": "ID",
            "Phone / Campaign": "Teléfono / Campaña",
            "Date": "Data",
            "Status": "Estado",
            "Results / Scores": "Resultados / Puntos",
            "Model": "Modelo",
            "Comments": "Comentarios",
            "More": "Máis",
            "No results found": "Non se atoparon resultados",
            "Completa": "Completa",
            "Incompleta": "Incompleta",
            "Rechazada": "Rexeitada",
            "Fallida": "Fallada",
            "No Contesta": "Non Contesta",
            "Pendiente": "Pendente",
            "Preguntas Abiertas": "Preguntas Abertas",
            "None": "Ningunha",
            "Retry": "Reintentar",
            "Transcript": "Transcrición",
            "Export CSV": "Exportar CSV"
        }
    }
};

i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
        resources,
        fallbackLng: "es",
        interpolation: {
            escapeValue: false
        }
    });

export default i18n;
