/** Formatos admitidos por POST /api/knowledge/upload (extracción en backend). */
export const KNOWLEDGE_FILE_ACCEPT =
  '.pdf,.docx,.xlsx,.xls,.jsonl,.txt,.md,.csv,.json';

export const KNOWLEDGE_FORMATS_LABEL =
  'PDF, Word (.docx), Excel (.xlsx/.xls), JSONL, JSON, CSV, Markdown y texto plano';

export function knowledgeSourceTypeFromFile(file: File): string {
  const ext = file.name.split('.').pop()?.toLowerCase() || '';
  if (ext === 'pdf') return 'pdf';
  if (ext === 'json') return 'json';
  if (ext === 'jsonl') return 'jsonl';
  return 'manual';
}

export function textFileFromContent(title: string, content: string): File {
  const safeName = `${title.trim() || 'documento'}.txt`;
  return new File([content], safeName, { type: 'text/plain;charset=utf-8' });
}
