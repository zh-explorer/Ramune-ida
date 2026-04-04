/**
 * Lightweight x86 disassembly operand highlighter.
 * Each token gets data-token for click-to-highlight.
 */

const REGS = new Set([
  "rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
  "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15",
  "eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp",
  "ax", "bx", "cx", "dx", "si", "di", "bp", "sp",
  "al", "bl", "cl", "dl", "ah", "bh", "ch", "dh",
  "sil", "dil", "bpl", "spl",
  "cs", "ds", "es", "fs", "gs", "ss",
  "xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7",
]);

const TOKEN_RE =
  /(\b0[xX][0-9A-Fa-f]+h?\b|\b[0-9][0-9A-Fa-f]*h\b|\b\d+\b)|(\b(?:sub_|loc_|off_|unk_|dword_|qword_|byte_|asc_)[0-9A-Fa-f]+\b)|(\b[a-z]\w*\b)|(;.*$)|(\[|\])|([,+*\-:])/g;

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

export function highlightOps(
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

    const [full, num, idaName, ident, comment] = match;

    if (comment) {
      parts.push(<span key={match.index} className="hl-comment">{full}</span>);
    } else if (num) {
      parts.push(tok(match.index, "hl-num", full, activeToken));
    } else if (idaName) {
      parts.push(tok(match.index, "hl-func", full, activeToken));
    } else if (ident) {
      const cls = REGS.has(ident) ? "asm-reg" : "hl-ident";
      parts.push(tok(match.index, cls, full, activeToken));
    } else {
      parts.push(<span key={match.index} className="hl-punct">{full}</span>);
    }

    lastIndex = match.index + full.length;
  }

  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex));
  }

  return parts;
}
