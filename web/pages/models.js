// 模型页（零依赖原生 ESM）：已安装模型管理 + 推荐模型目录 + 拉取/删除 + 进度。
import { store } from '../store.js';
import { api, toUserError, UserError } from '../api.js';
import { qs, el, clear, copyText } from '../ui/dom.js';
import { showToast } from '../ui/toast.js';
import { confirmModal } from '../ui/modal.js';
import { progressBar, setProgress } from '../ui/progressBar.js';
import { emptyState } from '../ui/emptyState.js';

let refs = null;

function humanSize(bytes) {
  if (!bytes) return '—';
  const gb = bytes / (1024 ** 3);
  if (gb >= 1) return gb.toFixed(1) + ' GB';
  const mb = bytes / (1024 ** 2);
  return mb.toFixed(0) + ' MB';
}

async function refreshInstalled() {
  try {
    const r = await api.models();
    store.set({ models: (r && r.models) || [] });
  } catch (e) { /* 非致命 */ }
  renderInstalled();
}

function renderInstalled() {
  const box = qs('#models-installed');
  if (!box) return;
  clear(box);
  const models = store.get().models || [];
  if (!models.length) {
    box.appendChild(emptyState('还没有已安装模型。在下方「推荐模型」里拉取一个，或去部署向导完成一键部署。'));
    return;
  }
  for (const m of models) {
    const pull = store.get().pull;
    const pulling = pull && pull.name === m.name;

    const sub = [
      m.parameter_size || '',
      m.family || '',
      m.quantization || '',
      humanSize(m.size),
    ].filter(Boolean).join(' · ');

    const delBtn = el('button', { class: 'btn sm danger', text: '删除', on: { click: () => delModel(m.name) } });
    const row = el('div', { class: 'model-row' },
      el('div', { class: 'info' },
        el('div', { class: 'name', text: m.name }),
        el('div', { class: 'sub', text: sub })
      ),
      delBtn
    );
    if (pulling) row.appendChild(progressBar(pull.total ? Math.round((pull.completed / pull.total) * 100) : 0));
    box.appendChild(row);
  }
}

async function delModel(name) {
  const ok = await confirmModal({
    title: '删除模型',
    body: `确定删除本地模型「${name}」吗？该操作不可恢复。`,
    confirmText: '删除', danger: true,
  });
  if (!ok) return;
  try {
    await api.deleteModel(name);
    showToast('已删除：' + name, 'ok');
    await refreshInstalled();
  } catch (e) {
    showToast(await toUserError(e));
  }
}

async function pullModel(name) {
  // 防止重复拉取同一模型（store.pull 表示进行中任务）
  const pull = store.get().pull;
  if (pull && pull.name === name) return;
  try {
    await api.pullModel(name);
    showToast('开始拉取：' + name, 'ok');
    store.set({ pull: { name, completed: 0, total: 0 } });
    renderInstalled();
    renderCatalog(); // 同步目录里的按钮态
  } catch (e) {
    const ue = await toUserError(e);
    if (ue.code === 'PULL_IN_PROGRESS') {
      showToast('已有拉取任务进行中', 'warn');
    } else {
      showToast(ue);
    }
  }
}

async function refreshCatalog() {
  const hw = store.get().hardware;
  const profile = hw && hw.profile ? hw.profile.profile_id : '';
  try {
    const r = await api.modelsAvailable(profile);
    store.set({ catalog: (r && r.models) || [] });
  } catch (e) { /* 非致命 */ }
  renderCatalog();
}

function renderCatalog() {
  const box = qs('#models-catalog');
  if (!box) return;
  clear(box);
  const catalog = store.get().catalog || [];
  const pull = store.get().pull;
  if (!catalog.length) {
    box.appendChild(emptyState('暂时没有可推荐的模型。'));
    return;
  }
  for (const c of catalog) {
    const sub = [
      c.size_gb ? c.size_gb.toFixed(1) + ' GB' : '',
      '最低内存 ' + (c.min_ram_gb || '?') + ' GB',
    ].filter(Boolean).join(' · ');

    const pulling = pull && pull.name === c.name;
    const pullBtn = el('button', {
      class: 'btn sm primary',
      text: pulling ? '拉取中…' : '拉取',
      disabled: !!pulling,
      on: { click: () => pullModel(c.name) },
    });

    const tags = [];
    if (c.recommended) tags.push(el('span', { class: 'tag ok', text: '推荐' }));
    if (c.tags && c.tags.length) {
      for (const t of c.tags.slice(0, 3)) tags.push(el('span', { class: 'tag', text: t }));
    }

    const row = el('div', { class: 'model-row' },
      el('div', { class: 'info' },
        el('div', { class: 'row', style: { gap: '6px', alignItems: 'center' } },
          el('span', { class: 'name', text: c.name }),
          ...tags
        ),
        el('div', { class: 'sub', text: sub + (c.recommended_for ? ' · ' + c.recommended_for : '') })
      ),
      pullBtn
    );
    box.appendChild(row);
  }
}

function renderPullProgress() {
  const pull = store.get().pull;
  renderInstalled();
  renderCatalog();
  if (!pull) return;
  // 已在 renderInstalled/renderCatalog 中按 name 渲染进度条
}

export function init() {
  const root = qs('#view-models');
  clear(root);

  const installedBox = el('div', { id: 'models-installed' });
  const catalogBox = el('div', { id: 'models-catalog' });

  root.appendChild(el('div', {},
    el('h2', { class: 'view-title', text: '模型' }),
    el('div', { class: 'panel', style: { marginBottom: '16px' } },
      el('h3', { text: '已安装模型' }),
      installedBox
    ),
    el('div', { class: 'panel' },
      el('h3', { text: '推荐模型' }),
      el('div', { class: 'muted', text: '依据本机硬件剖面推荐；点击「拉取」后台下载，进度显示在已安装列表。' }),
      catalogBox
    )
  ));

  refs = { installedBox, catalogBox };

  refreshInstalled();
  refreshCatalog();

  // 拉取进度 / 完成事件经 WS 写入 store.pull
  store.subscribe((s) => {
    renderPullProgress();
  });

  // 暴露给 ws 可能需要的刷新（此处不强制）
  if (root.__modelsSub) root.__modelsSub();
  root.__modelsSub = () => {};
}
