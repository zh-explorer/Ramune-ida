/**
 * Lightweight C pseudocode syntax highlighter.
 * Each token gets a data-token attribute for click-to-highlight.
 */

const C_KEYWORDS = new Set([
  "auto", "break", "case", "char", "const", "continue", "default", "do",
  "double", "else", "enum", "extern", "float", "for", "goto", "if",
  "int", "long", "register", "return", "short", "signed", "sizeof",
  "static", "struct", "switch", "typedef", "union", "unsigned", "void",
  "volatile", "while", "bool", "true", "false", "nullptr", "NULL",
  "__int8", "__int16", "__int32", "__int64", "__fastcall", "__cdecl",
  "__stdcall", "__thiscall", "_BYTE", "_WORD", "_DWORD", "_QWORD",
  "_BOOL", "LOBYTE", "HIBYTE", "LOWORD", "HIWORD",
]);

const TOKEN_RE =
  /("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(\b0x[0-9A-Fa-f]+\b|\b\d+\b)|(\b[A-Za-z_]\w*\b)|(\/\/.*$)|([^\w\s"']+)/g;

function tok(
  key: number,
  cls: string,
  text: string,
  activeToken: string | null,
): React.ReactElement {
  const isActive = activeToken !== null && text === activeToken;
  return (
    <span
      key={key}
      className={`${cls}${isActive ? " token-hl" : ""}`}
      data-token={text}
    >
      {text}
    </span>
  );
}

export function highlightC(
  text: string,
  activeToken: string | null = null,
): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;

  TOKEN_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = TOKEN_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.substring(lastIndex, match.index));
    }

    const [full, str, num, ident, comment] = match;

    if (str) {
      parts.push(tok(match.index, "hl-str", full, activeToken));
    } else if (comment) {
      parts.push(tok(match.index, "hl-comment", full, null));
    } else if (num) {
      parts.push(tok(match.index, "hl-num", full, activeToken));
    } else if (ident) {
      const cls = C_KEYWORDS.has(ident)
        ? "hl-kw"
        : ident.startsWith("sub_") || ident.startsWith("loc_")
          ? "hl-func"
          : "hl-ident";
      parts.push(tok(match.index, cls, full, activeToken));
    } else {
      // punctuation — not clickable
      parts.push(<span key={match.index} className="hl-punct">{full}</span>);
    }

    lastIndex = match.index + full.length;
  }

  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex));
  }

  return parts;
}
