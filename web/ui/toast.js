// 全局轻提示（零依赖）
import { qs, el } from './dom.js';
import { UserError } from '../api.js';

// showToast(message, kind='info', duration=4000)
// message 可为字符串或 UserError（自动取 .title/.detail）。
// kind: 'info' | 'ok' | 'warn' | 'error'
export function showToast(message, kind = 'info', duration = 4000) {
  const root = qs('#toast-root');
  if (!root) return null;

  let title = '';
  let detail = '';
  let k = kind;

  if (message instanceof UserError) {
    title = message.title || '出错';
    detail = message.detail || '';
    if (!k || k === 'info') k = 'error';
  } else {
    title = String(message);
  }

  const cls = ['toast'];
  if (k && k !== 'info') cls.push(k);

  const children = [el('div', { class: 'toast-title', text: title })];
  if (detail) children.push(el('div', { class: 'toast-detail', text: detail }));

  const node = el('div', {
    class: cls.join(' '),
    role: k === 'error' ? 'alert' : 'status',
  }, ...children);

  const remove = () => { if (node.parentNode) node.parentNode.removeChild(node); };
  node.addEventListener('click', remove);
  if (duration > 0) setTimeout(remove, duration);
  root.appendChild(node);
  return node;
}
