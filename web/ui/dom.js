// 极简 DOM 构建工具（零依赖原生 ESM）
// 工程红线：所有外部/不可信文本一律 textContent，禁止 innerHTML 拼接不可信内容。

// 创建元素：el(tag, props?, ...children)
// props 支持：class/className、text、html(仅可信静态串)、dataset、style(object)、
//            on{事件名: fn}、布尔/字符串属性（hidden/disabled/value/role/aria-* 等）。
// children：字符串/数字→文本节点；节点直接追加；数组会展开；null/false 跳过。
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v == null) continue;
      if (k === 'class' || k === 'className') {
        node.className = v;
      } else if (k === 'text') {
        node.textContent = v;
      } else if (k === 'html') {
        // 仅用于可信静态模板字符串；绝不传入后端/模型输出
        node.innerHTML = v;
      } else if (k === 'dataset' && typeof v === 'object') {
        Object.assign(node.dataset, v);
      } else if (k === 'style' && typeof v === 'object') {
        Object.assign(node.style, v);
      } else if (k === 'on' && typeof v === 'object') {
        for (const [evt, fn] of Object.entries(v)) {
          if (typeof fn === 'function') node.addEventListener(evt, fn);
        }
      } else if (k in node && k !== 'list') {
        try { node[k] = v; } catch { node.setAttribute(k, v); }
      } else {
        node.setAttribute(k, v);
      }
    }
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    if (typeof c === 'string' || typeof c === 'number') {
      node.appendChild(document.createTextNode(String(c)));
    } else {
      node.appendChild(c);
    }
  }
  return node;
}

export function qs(sel, root = document) {
  return root.querySelector(sel);
}

export function qsa(sel, root = document) {
  return Array.from(root.querySelectorAll(sel));
}

export function clear(node) {
  if (!node) return;
  while (node.firstChild) node.removeChild(node.firstChild);
}

// 仅用于可信静态 HTML 模板（不传不可信文本）
export function mount(node, html) {
  if (!node) return;
  node.innerHTML = html;
}

export function on(node, evt, fn) {
  if (node) node.addEventListener(evt, fn);
}

// 复制到剪贴板（带 textarea 兜底）
export function copyText(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(() => fallbackCopy(text));
      return;
    }
  } catch { /* fall through */ }
  fallbackCopy(text);
}

function fallbackCopy(text) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  } catch { /* ignore */ }
}
