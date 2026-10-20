// WebSocket 事件客户端（零依赖原生 ESM）
// 连接 /ws/events，指数退避重连（1s→2s→4s…→30s 封顶 + ±20% jitter），解析 JSON 信封并分发。
import { store } from './store.js';
import { api, toUserError } from './api.js';
import { showToast } from './ui/toast.js';

// 更新某一步骤的状态（按 name 匹配）
function updateStep(steps, name, patch) {
  return (steps || []).map((s) => (s.name === name ? { ...s, ...patch } : s));
}

async function refreshModels() {
  try {
    const r = await api.models();
    store.set({ models: (r && r.models) || [] });
  } catch { /* 非致命，忽略 */ }
}
async function refreshBackends() {
  try {
    const r = await api.backends();
    store.set({ backends: r });
  } catch { /* 忽略 */ }
}
async function refreshHealthDeep() {
  try {
    const r = await api.healthDeep();
    store.set({ health: r });
  } catch { /* 忽略 */ }
}

// connectEvents(onEvent, onStatus)
//  - onEvent({type, payload})：全局事件回调（WS 内部已处理 store 更新）
//  - onStatus(status)：'connecting' | 'online' | 'offline'
// 返回 { close() }
export function connectEvents(onEvent, onStatus) {
  let ws = null;
  let retries = 0;
  let stopped = false;
  let timer = null;

  function makeUrl() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return proto + '//' + location.host + '/ws/events';
  }

  function reconnect() {
    if (stopped) return;
    const base = Math.min(30000, 1000 * Math.pow(2, retries));
    const jitter = base * 0.2 * (Math.random() * 2 - 1);
    const delay = Math.max(500, Math.round(base + jitter));
    retries += 1;
    store.set({ ws: 'connecting' });
    if (onStatus) onStatus('connecting');
    timer = setTimeout(connect, delay);
  }

  function connect() {
    if (stopped) return;
    let sock;
    try {
      sock = new WebSocket(makeUrl());
    } catch {
      reconnect();
      return;
    }
    ws = sock;

    sock.onopen = () => {
      retries = 0;
      store.set({ ws: 'online' });
      if (onStatus) onStatus('online');
    };

    sock.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      const type = msg && msg.type;
      const payload = (msg && msg.payload) || {};

      // —— 以下事件直接更新 store ——
      if (type === 'setup.started') {
        store.set((s) => ({
          setup: {
            runId: payload.run_id,
            status: 'running',
            steps: (payload.steps || []).map((n) => ({ name: n, status: 'pending' })),
            error: null,
          },
        }));
      } else if (type === 'setup.step_progress') {
        store.set((s) => ({
          setup: {
            ...s.setup,
            steps: updateStep(s.setup.steps, payload.step, {
              status: 'running', message: payload.message, percent: payload.percent,
            }),
          },
        }));
      } else if (type === 'setup.step_done') {
        store.set((s) => ({
          setup: {
            ...s.setup,
            steps: updateStep(s.setup.steps, payload.step, { status: 'done', duration_ms: payload.duration_ms }),
          },
        }));
      } else if (type === 'setup.error') {
        store.set((s) => ({ setup: { ...s.setup, status: 'failed', error: payload } }));
      } else if (type === 'model.pull_progress') {
        store.set((s) => ({ pull: { ...(s.pull || {}), ...payload } }));
      } else if (type === 'model.pull_done') {
        refreshModels();
        store.set({ pull: null });
        if (payload && payload.model) showToast('拉取完成：' + payload.model, 'ok');
      } else if (type === 'backend.changed') {
        refreshBackends();
        store.set((s) => ({ system: s.system ? { ...s.system, active_backend: payload.active } : s.system }));
      } else if (type === 'health.changed') {
        refreshHealthDeep();
      } else if (type === 'error') {
        showToast(toUserError(payload), 'error');
      } else if (type === 'log.line') {
        // 忽略（或 console.debug）：向导页以 step_progress.message 为准
        console.debug('[log]', payload && payload.message);
      }

      if (onEvent) onEvent({ type, payload });
    };

    sock.onclose = () => {
      if (stopped) return;
      store.set({ ws: 'offline' });
      if (onStatus) onStatus('offline');
      reconnect();
    };

    sock.onerror = () => {
      store.set({ ws: 'offline' });
      if (onStatus) onStatus('offline');
    };
  }

  connect();

  return {
    close() {
      stopped = true;
      if (timer) clearTimeout(timer);
      if (ws) { try { ws.close(); } catch { /* ignore */ } }
    },
  };
}
