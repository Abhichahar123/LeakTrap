// Safe DOM helpers: every value is inserted as text, never parsed as HTML.

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === "object" && "nodeType" in child ? child : String(child));
  }
  return node;
}

export function show(container, ...children) {
  container.replaceChildren(...children.flat().filter(Boolean));
}

export function definitionList(rows) {
  return el("dl", {}, rows.flatMap(([term, value]) => [el("dt", {}, term), el("dd", {}, value)]));
}
