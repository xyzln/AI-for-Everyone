// 进度条（零依赖），复用 style.css 的 .progress / .progress > i
import { el } from './dom.js';

// 创建进度条，返回容器节点（.progress）
export function progressBar(percent = 0) {
  const fill = el('i', {});
  const bar = el('div', { class: 'progress' }, fill);
  setProgress(bar, percent);
  return bar;
}

// 设置百分比（0-100）
export function setProgress(node, pct) {
  if (!node) return;
  const fill = node.querySelector('i') || node;
  const v = Math.max(0, Math.min(100, Number(pct) || 0));
  fill.style.width = v + '%';
}

export function setIndeterminate(node, on) {
  if (!node) return;
  node.classList.toggle('indeterminate', !!on);
}
