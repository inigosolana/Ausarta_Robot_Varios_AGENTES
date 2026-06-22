import DOMPurify from 'dompurify';

/** Sanitiza HTML antes de dangerouslySetInnerHTML (p. ej. salida del LLM). */
export function sanitizeAssistantHtml(content: string): string {
  const withBreaks = content.replace(/\n/g, '<br/>');
  return DOMPurify.sanitize(withBreaks, {
    ALLOWED_TAGS: ['b', 'i', 'em', 'strong', 'a', 'br', 'p', 'ul', 'ol', 'li', 'code', 'pre'],
    ALLOWED_ATTR: ['href', 'target', 'rel'],
  });
}
