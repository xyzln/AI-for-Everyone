// 聊天页（零依赖原生 ESM）：模型选择、参数、流式对话、中断。
import { store } from '../store.js';
import { api, toUserError, readSSE, UserError } from '../api.js';
import { qs, el, clear } from '../ui/dom.js';
import { showToast } from '../ui/toast.js';
import { makeBubble, appendDelta, finalizeBubble } from '../ui/streamRenderer.js';
import { emptyState } from '../ui/emptyState.js';

let refs = null;
let messages = [];        // 当前会话消息：[{role, content}]
let controller = null;     // 当前流式请求的 AbortController
let currentModel = null;   // 选中的模型名

function activeModelName() {
  // 优先用选择器里选中的；否则用后端激活后端默认模型（store.system 暂无，则用首个已装模型）
  const sel = qs('#chat-model');
  if (sel && sel.value) return sel.value;
  if (currentModel) return currentModel;
  const installed = (store.get().models || []);
  return installed.length ? installed[0].name : null;
}

async function refreshModels(force) {
  if (force || !store.get().models || !store.get().models.length) {
    try {
      const r = await api.models();
      store.set({ models: (r && r.models) || [] });
    } catch (e) { /* 非致命 */ }
  }
  renderModelOptions();
}

function renderModelOptions() {
  const sel = qs('#chat-model');
  if (!sel) return;
  const installed = (store.get().models || []);
  const prev = sel.value || currentModel;
  clear(sel);
  if (!installed.length) {
    sel.appendChild(el('option', { value: '', text: '（暂无已安装模型）' }));
    currentModel = null;
    return;
  }
  for (const m of installed) {
    sel.appendChild(el('option', { value: m.name, text: m.name }));
  }
  // 尽量保留上次选择
  if (prev && installed.some((m) => m.name === prev)) sel.value = prev;
  currentModel = sel.value || installed[0].name;
}

function appendMessage(role, content) {
  const bubble = makeBubble(role);
  const textEl = bubble.querySelector('.text');
  if (content) textEl.textContent = content;
  refs.log.appendChild(bubble);
  refs.log.scrollTop = refs.log.scrollHeight;
  return bubble;
}

function setBusy(busy) {
  refs.sendBtn.disabled = busy;
  refs.stopBtn.disabled = !busy;
  refs.input.disabled = busy;
  refs.modelSel.disabled = busy;
}

async function send() {
  const text = (refs.input.value || '').trim();
  if (!text) return;

  // 移除初始空态提示（如有）
  const empty = refs.log.querySelector('.empty');
  if (empty) empty.remove();

  const model = activeModelName();
  if (!model) {
    showToast(new UserError('MODEL_NOT_FOUND', '还没有可用的模型', '请先到「模型」页拉取一个模型', '去模型页'));
    return;
  }

  // 渲染用户消息并清空输入
  appendMessage('user', text);
  messages.push({ role: 'user', content: text });
  refs.input.value = '';

  // 创建 assistant 气泡（流式）
  const bubble = makeBubble('assistant');
  bubble.classList.add('streaming');
  bubble.setAttribute('aria-busy', 'true');
  refs.log.appendChild(bubble);
  refs.log.scrollTop = refs.log.scrollHeight;

  setBusy(true);
  controller = new AbortController();

  const opts = store.get().chatOptions || {};
  const body = {
    model,
    messages: messages.slice(),
    options: {
      temperature: Number(opts.temperature ?? 0.7),
      top_p: Number(opts.top_p ?? 0.9),
      num_ctx: Number(opts.num_ctx ?? 4096),
    },
    stream: true,
  };

  try {
    const res = await api.chatStream(body, controller.signal);
    if (!res.ok) { showToast(await toUserError(res)); finishWithError(bubble); return; }

    let usage = null;
    await readSSE(res, ({ event, data }) => {
      if (event === 'delta' && data) {
        appendDelta(bubble, data.delta || '');
      } else if (event === 'usage' && data) {
        usage = data;
      } else if (event === 'done') {
        finalizeBubble(bubble, usage);
      } else if (event === 'error' && data) {
        finalizeBubble(bubble, null);
        showToast(new UserError(data.code || 'INTERNAL_ERROR', data.message || '推理出错', '', '重试'));
        bubble.classList.add('failed');
      }
    });

    // 收尾：把 assistant 内容并入会话历史
    const textEl = bubble.querySelector('.text');
    const assistantText = textEl ? textEl.textContent : '';
    messages.push({ role: 'assistant', content: assistantText });
  } catch (e) {
    if (e.name === 'AbortError') {
      bubble.classList.add('interrupted');
      // 中断后仍保留已生成内容
      const textEl = bubble.querySelector('.text');
      const assistantText = textEl ? textEl.textContent : '';
      if (assistantText) messages.push({ role: 'assistant', content: assistantText });
    } else {
      showToast(await toUserError(e));
      finishWithError(bubble);
    }
  } finally {
    setBusy(false);
    controller = null;
    bubble.classList.remove('streaming');
    bubble.removeAttribute('aria-busy');
    refs.input.focus();
  }
}

function finishWithError(bubble) {
  bubble.classList.remove('streaming');
  bubble.classList.add('failed');
}

function stop() {
  if (controller) controller.abort();
}

function clearChat() {
  messages = [];
  clear(refs.log);
}

export function init() {
  const root = qs('#view-chat');
  clear(root);

  const modelSel = el('select', { id: 'chat-model', class: 'select', on: { change: (e) => { currentModel = e.target.value; } } });
  const tempInput = el('input', { type: 'range', min: '0', max: '2', step: '0.1', value: String((store.get().chatOptions || {}).temperature ?? 0.7), class: 'range', on: {
    input: (e) => {
      const v = Number(e.target.value);
      store.set((s) => ({ chatOptions: { ...s.chatOptions, temperature: v } }));
      const lbl = qs('#temp-val'); if (lbl) lbl.textContent = v.toFixed(1);
    },
  } });
  const tempVal = el('span', { id: 'temp-val', text: ((store.get().chatOptions || {}).temperature ?? 0.7).toFixed(1), class: 'muted' });

  const input = el('textarea', { id: 'chat-input', placeholder: '输入消息，回车发送（Shift+Enter 换行）', on: {
    keydown: (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    },
  } });
  const sendBtn = el('button', { class: 'btn primary', id: 'chat-send', on: { click: send } }, '发送');
  const stopBtn = el('button', { class: 'btn', id: 'chat-stop', disabled: true, on: { click: stop } }, '中断');
  const clearBtn = el('button', { class: 'btn', id: 'chat-clear', on: { click: clearChat } }, '清空');

  const bar = el('div', { class: 'chat-bar' },
    el('label', { class: 'muted', text: '模型' }),
    modelSel,
    el('label', { class: 'muted', text: '温度' }),
    tempInput,
    tempVal
  );

  const log = el('div', { class: 'chat-log', id: 'chat-log', role: 'log', 'aria-live': 'polite' });
  const inputRow = el('div', { class: 'chat-input' }, input, sendBtn, stopBtn, clearBtn);

  const wrap = el('div', { class: 'chat-wrap' },
    el('h2', { class: 'view-title', text: '聊天' }),
    bar,
    log,
    inputRow
  );

  root.appendChild(wrap);

  refs = { log, input, sendBtn, stopBtn, modelSel, clearBtn };

  // 先展示已有会话（无则空态），再拉取模型列表
  if (messages.length) {
    for (const m of messages) appendMessage(m.role, m.content);
  } else {
    log.appendChild(emptyState('还没有对话。在上方选择模型并输入消息开始。'));
  }

  refreshModels(false);
  // 模型列表变化时刷新选择器
  const unsub = store.subscribe((s) => {
    if (s.models && Array.isArray(s.models)) renderModelOptions();
  });
  // 仅首次 init 注册一次即可；后续 refresh 已处理
  if (root.__chatSub) root.__chatSub();
  root.__chatSub = unsub;
}
