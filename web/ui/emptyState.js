// 空态 / 错误态（零依赖），复用 style.css 的 .empty / .error-box / .muted
import { el } from './dom.js';
import { UserError } from '../api.js';

// emptyState(text, action?) -> div.empty
export function emptyState(text, action) {
  const node = el('div', { class: 'empty' }, text || '暂无数据');
  if (action) node.appendChild(action);
  return node;
}

// errorState(err, onRetry?) -> div.error-box
// err: UserError | string | Error
export function errorState(err, onRetry) {
  let title = '出错了';
  let detail = '';
  if (err instanceof UserError) {
    title = err.title || '出错了';
    detail = err.detail || '';
  } else if (typeof err === 'string') {
    title = err;
  } else if (err && err.message) {
    title = err.message;
  }
  const node = el('div', { class: 'error-box' },
    el('div', { text: title }),
    detail ? el('div', { class: 'muted', text: detail }) : null
  );
  if (typeof onRetry === 'function') {
    node.appendChild(el('button', { class: 'btn', style: { marginTop: '8px' }, on: { click: onRetry } }, '重试'));
  }
  return node;
}
