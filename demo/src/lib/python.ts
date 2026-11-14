/** A small Python tokenizer for syntax colouring. Enough for ast.unparse output. */
const KEYWORDS = new Set(
  "and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case".split(" "),
);
const CONSTS = new Set(["True", "False", "None", "self", "cls"]);

export type Tok = [cls: string, text: string];
const RE =
  /(#[^\n]*)|((?:[rbfRBF]{0,2})(?:"""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'))|(\b\d[\d_.]*(?:e[+-]?\d+)?\b)|(@[\w.]+)|([A-Za-z_]\w*)|(\s+)|([^\sA-Za-z_0-9#"']+)/g;

export function tokenize(code: string): Tok[] {
  const out: Tok[] = [];
  let m: RegExpExecArray | null;
  RE.lastIndex = 0;
  let prev = "";
  while ((m = RE.exec(code))) {
    if (m[1]) out.push(["c", m[1]]);
    else if (m[2]) out.push(["s", m[2]]);
    else if (m[3]) out.push(["n", m[3]]);
    else if (m[4]) out.push(["d", m[4]]);
    else if (m[5]) {
      const w = m[5];
      const after = code[RE.lastIndex];
      if (KEYWORDS.has(w)) out.push(["k", w]);
      else if (CONSTS.has(w)) out.push(["b", w]);
      else if (prev === "def" || prev === "class") out.push(["f", w]);
      else if (after === "(") out.push(["call", w]);
      else out.push(["", w]);
      prev = w;
    } else out.push(["", m[0]]);
    if (m[0].length === 0) RE.lastIndex++;
  }
  return out;
}

/** Tokens grouped per source line. */
export function tokenizeLines(code: string): Tok[][] {
  const lines: Tok[][] = [[]];
  for (const [cls, text] of tokenize(code)) {
    const parts = text.split("\n");
    parts.forEach((p, i) => {
      if (i > 0) lines.push([]);
      if (p) lines[lines.length - 1].push([cls, p]);
    });
  }
  return lines;
}
