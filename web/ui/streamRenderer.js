// 流式消息渲染辅助（零依赖）
// 配合聊天页的 .msg.assistant 气泡：appendDelta 增量追加文本，finalizeBubble 收尾。
import { el } from './dom.js';

// 向气泡内追加增量文本（容错兼容 delta/content/text 三种字段名）。
export function appendDelta(bubbleEl, text) {
  if (!bubbleEl || text == null) return;
  let textEl = bubbleEl.querySelector('.text');
  if (!textEl) {
    textEl = el('div', { class: 'text' });
    bubbleEl.appendChild(textEl);
  }
  textEl.textContent += text;
  // 自动贴底
  const log = bubbleEl.closest('.chat-log');
  if (log) log.scrollTop = log.scrollHeight;
}

// 收尾：去掉流式中状态，可选附加 usage 脚注。
export function finalizeBubble(bubbleEl, usage) {
  if (!bubbleEl) return;
  bubbleEl.classList.remove('streaming');
  bubbleEl.removeAttribute('aria-busy');
  if (usage) {
    const u = usage.usage || usage;
    const total = u.total_tokens != null ? u.total_tokens
      : (u.completion_tokens != null ? u.completion_tokens : null);
    if (total != null) {
      bubbleEl.appendChild(el('div', { class: 'usage', text: `${total} tokens` }));
    }
  }
}

// 创建一条消息气泡（role: 'user' | 'assistant' | 'system'）
export function makeBubble(role, label) {
  return el('div', { class: 'msg ' + role },
    el('div', { class: 'role', text: label || (role === 'user' ? '你' : 'AI') }),
    el('div', { class: 'text' })
  );
}
