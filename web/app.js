// 应用入口（零依赖原生 ESM）：标签切换、初始数据拉取、WebSocket 状态、状态栏。
import { store } from './store.js';
import { api } from './api.js';
import { qs, qsa } from './ui/dom.js';
import { connectEvents } from './ws.js';
import { renderHealthBadge } from './ui/healthBadge.js';

import { init as initWizard } from './pages/wizard.js';
import { init as initChat } from './pages/chat.js';
import { init as initModels } from './pages/models.js';
import { init as initStatus } from './pages/status.js';

const PAGES = {
  wizard: initWizard,
  chat: initChat,
  models: initModels,
  status: initStatus,
};
const initialized = new Set();

function updateReadyBanner() {
  const banner = qs('#ready-banner');
  const text = qs('#ready-banner-text');
  if (!banner || !text) return;
  const h = store.get().health;
  if (!h || typeof h.healthy !== 'boolean' || h.healthy) {
    banner.hidden = true;
    return;
  }
  // 未就绪：取首个失败检查项做说明，引导去部署（替代满屏“不可达”报错）
  const checks = h.checks || {};
  const failed = Object.values(checks).filter((c) => c && c.ok === false);
  const backend = failed.find((c) => c.name === 'backend' || c.name === 'ollama');
  const detail = (backend && backend.detail)
    || (failed.length ? failed.map((c) => c.name).join('、') + ' 未就绪' : '请检查状态页');
  text.textContent = `服务尚未就绪（${detail}）。首次使用请点「一键部署」安装 Ollama 并拉取模型。`;
  banner.hidden = false;
}

function updateStatusBar() {
  const s = store.get();

  // 版本号
  const ver = (s.system && s.system.version) || (s.health && s.health.version) || '?';
  const vlabel = qs('#version-label');
  if (vlabel) vlabel.textContent = 'v' + ver;

  // 健康徽章
  const hb = qs('#health-badge');
  if (hb) renderHealthBadge(hb, s.health);

  // WebSocket 指示灯
  const led = qs('#ws-led');
  if (led) {
    const ws = s.ws || 'connecting';
    led.className = 'led ' + (ws === 'online' ? 'open' : ws === 'offline' ? 'closed' : '');
    led.title = 'WebSocket：' + (
      ws === 'online' ? '已连接' : ws === 'offline' ? '已断开（正在自动重连）' : '连接中…'
    );
  }

  updateReadyBanner();
}

function selectTab(name) {
  if (!PAGES[name]) return;
  store.set({ view: name });
  qsa('.tab').forEach((t) => t.setAttribute('aria-selected', String(t.id === 'tab-' + name)));
  qsa('.view').forEach((v) => { v.hidden = (v.id !== 'view-' + name); });
  if (!initialized.has(name)) {
    try { PAGES[name](); } catch (e) { console.error('init page failed:', name, e); }
    initialized.add(name);
  }
}

function hideSplash() {
  const sp = qs('#splash');
  if (!sp) return;
  sp.classList.add('hide');
  setTimeout(() => { if (sp.parentNode) sp.parentNode.removeChild(sp); }, 450);
}

async function bootstrap() {
  // 首次并行拉取核心数据；任一失败不阻塞其它（WS 也会补偿刷新）。
  const tasks = [
    api.system().then((r) => store.set({ system: r })).catch(() => {}),
    api.hardware().then((r) => store.set({ hardware: r })).catch(() => {}),
    api.backends().then((r) => store.set({ backends: r })).catch(() => {}),
    api.models().then((r) => store.set({ models: (r && r.models) || [] })).catch(() => {}),
    api.healthDeep().then((r) => store.set({ health: r })).catch(() => {}),
  ];
  await Promise.allSettled(tasks);
  updateStatusBar();
}

function main() {
  qsa('.tab').forEach((t) => {
    t.addEventListener('click', () => selectTab(t.id.replace('tab-', '')));
  });

  const rbBtn = qs('#ready-banner-action');
  if (rbBtn) rbBtn.addEventListener('click', () => selectTab('wizard'));

  store.subscribe(updateStatusBar);

  connectEvents(
    () => { /* 全局事件已在 ws.js 内落盘到 store，这里无需额外处理 */ },
    () => { /* WS 状态已写入 store.ws，updateStatusBar 同步 */ }
  );

  bootstrap()
    .then(() => { selectTab('wizard'); hideSplash(); })
    .catch((e) => { console.error('bootstrap failed:', e); selectTab('wizard'); hideSplash(); });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', main);
} else {
  main();
}
