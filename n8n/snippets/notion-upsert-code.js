// Copia este bloque al inicio de cada nodo "Notion Upsert" en n8n.
// Edita NOTION_TOKEN y DATABASE_ID antes de activar el workflow.

const NOTION_TOKEN = 'PEGA_TU_NOTION_TOKEN';
const DATABASE_ID = 'PEGA_TU_DATABASE_ID';

const headers = {
  Authorization: `Bearer ${NOTION_TOKEN}`,
  'Notion-Version': '2022-06-28',
  'Content-Type': 'application/json',
};

function title(v) { return { title: [{ text: { content: String(v ?? '') } }] }; }
function txt(v) { return { rich_text: [{ text: { content: String(v ?? '') } }] }; }
function num(v) { return { number: v == null || v === '' ? null : Number(v) }; }
function sel(v) { return v ? { select: { name: String(v) } } : { select: null }; }
function chk(v) { return { checkbox: !!v }; }
function email(v) { return { email: v || null }; }
function date(v) { return v ? { date: { start: String(v).slice(0, 19) } } : { date: null }; }
