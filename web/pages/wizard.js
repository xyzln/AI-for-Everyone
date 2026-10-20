// 部署向导页（零依赖）
import { store } from '../store.js';
import { api, toUserError } from '../api.js';
import { qs, el, clear, copyText } from '../ui/dom.js';
import { showToast } from '../ui/toast.js';
import { confirmModal } from '../ui/modal.js';
import { progressBar } from '../ui/progressBar.js';

const STEP_LABELS = {
  deps: '依赖检查',
  hardware: '硬件探测',
  ollama: '安装并配置 Ollama',
  model: '拉取模型',
  verify: '推理验证',
  start: '启动服务',
};
const label = (name) => STEP_LABELS[name] || name;

let refs = null;
let navigated = false;

export function init() {
  const root = qs('#view-wizard');
  clear(root);

  const startBtn = el('button', { class: 'btn primary', id: 'wizard-start', on: { click: startDeploy } }, '开始一键部署');
  const redeployBtn = el('button', { class: 'btn', id: 'wizard-redeploy', on: { click: redeploy } }, '重新部署');
  const actions = el('div', { class: 'row', style: { justifyContent: 'flex-end', gap: '8px' } }, startBtn, redeployBtn);

  const note = el('div', { class: 'muted', id: 'wizard-note' });
  const stepsList = el('ul', { class: 'steps', id: 'wizard-steps' });
  const failWrap = el('div', { id: 'wizard-fail' });
  const logInner = el('div', { id: 'wizard-log', class: 'muted' });
  const logBox = el('details', { class: 'panel', style: { marginTop: '12px' } },
    el('summary', { text: '部署日志' }), logInner);

  root.appendChild(el('div', {},
    el('h2', { class: 'view-title', text: '部署向导' }),
    actions, note, stepsList, failWrap, logBox
  ));

  refs = {
    root, note, stepsList, failWrap, logInner, startBtn, redeployBtn,
  };

  loadStatus();
  store.subscribe(render);
  render();
}

async function loadStatus() {
  try {
    const st = await api.setupStatus();
    store.set({
      setup: {
        runId: st.run_id, status: st.status,
        steps: normalizeSteps(st.steps), error: null,
      },
    });
  } catch (e) {
    const ue = await toUserError(e);
    if (ue.code === 'SETUP_NOT_FOUND') {
      store.set({ setup: { runId: null, status: 'idle', steps: [], error: null } });
    } else {
      showToast(ue);
    }
  }
}

function normalizeSteps(steps) {
  return (steps || []).map((s) => ({
    name: s.name, status: s.status, message: s.message,
    duration_ms: s.duration_ms, error: s.error,
  }));
}

function render() {
  const s = store.get();
  const setup = s.setup || { status: 'idle', steps: [], error: null };

  // 顶部说明：设备检测状态
  if (!s.hardware) {
    refs.note.textContent = '正在检测设备…如长时间无响应，请确认 aife serve 正在运行。';
  } else {
    const p = s.hardware.profile;
    refs.note.textContent = p ? `当前硬件剖面：${p.profile_id}${p.experimental ? '（实验性）' : ''}` : '';
  }

  const running = setup.status === 'running';
  refs.startBtn.disabled = running;
  refs.redeployBtn.disabled = running;

  renderSteps(setup);
  renderFail(setup);
  renderLog(setup);

  // 全部完成后自动跳转到聊天页（仅一次）
  if (setup.status === 'done' && !navigated) {
    navigated = true;
    showToast('部署完成，去聊天吧', 'ok');
    setTimeout(() => { const t = qs('#tab-chat'); if (t) t.click(); }, 1200);
  } else if (setup.status !== 'done') {
    navigated = false;
  }
}

function renderSteps(setup) {
  clear(refs.stepsList);
  const steps = setup.steps || [];
  if (!steps.length) {
    refs.stepsList.appendChild(el('li', { class: 'muted', text: '还没有部署记录，点击「开始一键部署」开始。' }));
    return;
  }
  for (const step of steps) {
    const li = el('li', {
      class: 'step ' + (
        step.status === 'running' ? 'running'
          : step.status === 'done' ? 'done'
            : (step.status === 'failed' || step.status === 'error') ? 'failed' : ''
      ),
    });
    let dot = '•';
    if (step.status === 'done') dot = '✓';
    else if (step.status === 'running') dot = '…';
    else if (step.status === 'failed' || step.status === 'error') dot = '✕';
    li.appendChild(el('span', { class: 'dot', text: dot }));

    const meta = [];
    if (step.duration_ms != null) meta.push('耗时 ' + (step.duration_ms / 1000).toFixed(1) + 's');
    if (step.message) meta.push(step.message);
    li.appendChild(el('div', { class: 'label' },
      el('div', { text: label(step.name) }),
      meta.length ? el('div', { class: 'meta', text: meta.join(' · ') }) : null
    ));

    // 模型拉取步骤进行时显示进度条（数据来自 store.pull）
    if ((step.name === 'model' || step.name === 'pull') && step.status === 'running') {
      const pull = store.get().pull;
      const pct = pull && pull.total ? Math.round((pull.completed / pull.total) * 100) : 0;
      li.appendChild(progressBar(pct));
    }
    refs.stepsList.appendChild(li);
  }
}

function renderFail(setup) {
  clear(refs.failWrap);
  const err = setup.error;
  if (!err) return;

  const stepName = err.step ? label(err.step) : '部署';
  const codes = err.code ? `（${err.code}）` : '';
  const card = el('div', { class: 'fail-card' },
    el('div', { text: `✕ 第「${stepName}」步失败` }),
    el('div', { class: 'why', text: `${err.message || ''}${codes}` })
  );

  // remedy：兼容 string / array / {summary, commands}
  const remedy = err.remedy;
  if (remedy) {
    const commands = Array.isArray(remedy) ? remedy
      : (remedy.commands || (typeof remedy === 'string' ? [remedy] : []));
    if (commands.length) {
      card.appendChild(el('div', { class: 'muted', text: '怎么修（可复制执行）：' }));
      for (const cmd of commands) {
        card.appendChild(el('div', { class: 'cmd' },
          el('code', { text: cmd }),
          el('button', { class: 'btn sm', on: { click: () => copyText(cmd) } }, '复制')
        ));
      }
    }
    if (remedy.summary) card.appendChild(el('div', { class: 'muted', style: { marginTop: '4px' }, text: remedy.summary }));
  }

  card.appendChild(el('div', { class: 'row', style: { gap: '8px', marginTop: '8px' } },
    el('button', { class: 'btn', on: { click: retryStep } }, '重试本阶段'),
    el('button', { class: 'btn danger', on: { click: redeploy } }, '重新部署')
  ));
  refs.failWrap.appendChild(card);
}

function renderLog(setup) {
  clear(refs.logInner);
  const steps = setup.steps || [];
  if (!steps.length) {
    refs.logInner.appendChild(el('div', { text: '（暂无日志）' }));
    return;
  }
  for (const s of steps) {
    const line = `${label(s.name)}：${s.status}` +
      (s.message ? ' — ' + s.message : '') +
      (s.duration_ms != null ? ' (' + (s.duration_ms / 1000).toFixed(1) + 's)' : '');
    refs.logInner.appendChild(el('div', { text: line }));
  }
}

async function startDeploy() {
  try {
    const r = await api.setupRun({});
    store.set({ setup: { runId: r.run_id, status: 'running', steps: [], error: null } });
    showToast('部署已开始', 'ok');
  } catch (e) {
    const ue = await toUserError(e);
    if (ue.code === 'SETUP_RUNNING') {
      store.set((s) => ({ setup: { ...s.setup, status: 'running' } }));
    } else {
      showToast(ue);
    }
  }
}

async function redeploy() {
  const ok = await confirmModal({
    title: '重新部署', body: '将重新执行完整部署流程，已完成的阶段也会重跑。确定继续？',
    confirmText: '重新部署', danger: true,
  });
  if (!ok) return;
  try {
    const r = await api.setupRun({});
    store.set({ setup: { runId: r.run_id, status: 'running', steps: [], error: null } });
  } catch (e) {
    showToast(await toUserError(e));
  }
}

async function retryStep() {
  const setup = store.get().setup || {};
  const done = (setup.steps || [])
    .filter((s) => s.status === 'done' || s.status === 'skipped')
    .map((s) => s.name);
  try {
    const r = await api.setupRun({ skip: done });
    store.set((s) => ({ setup: { ...s.setup, status: 'running', error: null } }));
  } catch (e) {
    showToast(await toUserError(e));
  }
}
