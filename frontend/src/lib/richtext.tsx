/** Tiny, safe formatter for chatbot text: **bold** only. Everything else is rendered as plain text (no HTML injection). */
export function renderInline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') && part.length > 4
      ? <strong key={i}>{part.slice(2, -2)}</strong>
      : <span key={i}>{part}</span>);
}
