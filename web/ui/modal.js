// 模态框（零依赖，禁用原生 confirm/alert）
import { qs, el, clear } from './dom.js';

// showModal({ title, body, actions })
//  - body: 字符串或 DOM 节点
//  - actions: [{ label, kind?:'primary'|'danger'|'default', onClick?, close?:bool }]
// 返回 { close } 句柄。
export function showModal({ title, body, actions } = {}) {
  const root = qs('#modal-root');
  if (!root) return null;
  clear(root);

  const actionNodes = (actions || []).map((a) => {
    const cls = ['btn'];
    if (a.kind === 'primary') cls.push('primary');
    if (a.kind === 'danger') cls.push('danger');
    return el('button', {
      class: cls.join(' '),
      on: {
        click: () => {
          if (typeof a.onClick === 'function') a.onClick();
          if (a.close !== false) closeModal();
        },
      },
    }, a.label);
  });

  const children = [];
  if (title) children.push(el('h3', { text: title }));
  if (typeof body === 'string') children.push(el('div', { text: body }));
  else if (body) children.push(body);
  if (actionNodes.length) children.push(el('div', { class: 'actions' }, ...actionNodes));

  const modal = el('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true' }, ...children);
  root.appendChild(modal);
  root.classList.add('open');
  return { close: closeModal };
}

export function closeModal() {
  const root = qs('#modal-root');
  if (!root) return;
  root.classList.remove('open');
  clear(root);
}

// Promise 化确认框，便于 await。
export function confirmModal({
  title, body, confirmText = '确定', cancelText = '取消', danger = false, onConfirm,
} = {}) {
  return new Promise((resolve) => {
    showModal({
      title,
      body,
      actions: [
        { label: cancelText, kind: 'default', close: true, onClick: () => resolve(false) },
        {
          label: confirmText,
          kind: danger ? 'danger' : 'primary',
          close: true,
          onClick: () => { if (typeof onConfirm === 'function') onConfirm(); resolve(true); },
        },
      ],
    });
  });
}
