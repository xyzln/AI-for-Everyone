// 状态页（零依赖原生 ESM）：系统信息、健康检查、设备、后端、重启 Ollama。
import { store } from '../store.js';
import { api, toUserError } from '../api.js';
import { qs, el, clear } from '../ui/dom.js';
import { showToast } from '../ui/toast.js';
import { deviceCard } from '../ui/deviceCard.js';
import { renderHealthBadge } from '../ui/healthBadge.js';

function mapDevice(d) {
  if (!d) return null;
  return {
    type: d.kind,
    name: d.name,
    vram_gb: d.vram_gb,
    evidence: d.evidence,
    detail: [d.detail, d.driver_version ? '驱动 ' + d.driver_version : ''].filter(Boolean).join(' · '),
    caveats: [],
  };
}

function infoRow(label, value) {
  return el('div', { class: 'kv' },
    el('span', { class: 'k', text: label }),
    el('span', { class: 'v', text: value == null || value === '' ? '—' : String(value) })
  );
}

function renderSystem(sys) {
  const box = qs('#status-system');
  if (!box) return;
  clear(box);
  if (!sys) { box.appendChild(el('div', { class: 'muted', text: '暂无系统信息' })); return; }
  box.appendChild(infoRow('版本', sys.version));
  box.appendChild(infoRow('平台', sys.platform));
  box.appendChild(infoRow('Python', sys.python));
  box.appendChild(infoRow('硬件剖面', sys.profile));
  box.appendChild(infoRow('活跃后端', sys.active_backend));
  box.appendChild(infoRow('Ollama 版本', sys.ollama_version));
  box.appendChild(infoRow('CPU 核数', sys.cpu_cores));
  box.appendChild(infoRow('系统内存', sys.system_ram_gb != null ? sys.system_ram_gb.toFixed(1) + ' GB' : null));
}

function renderHealth(health) {
  const box = qs('#status-health');
  if (!box) return;
  clear(box);

  const badgeWrap = el('div', { style: { marginBottom: '8px' } });
  renderHealthBadge(badgeWrap, health);
  box.appendChild(badgeWrap);

  const checks = (health && health.checks) || {};
  const names = Object.keys(checks);
  if (!names.length) {
    box.appendChild(el('div', { class: 'muted', text: '无检查项' }));
    return;
  }
  for (const name of names) {
    const c = checks[name];
    const cls = 'check ' + (c.ok ? 'ok' : 'bad');
    const sev = c.severity && c.severity !== 'info' ? ` [${c.severity}]` : '';
    box.appendChild(el('div', { class: 'list-row' },
      el('div', { class: 'info' },
        el('div', { class: 'name' },
          el('span', { class: cls, text: (c.ok ? '✔ ' : '✘ ') + name }),
          sev ? el('span', { class: 'muted', text: sev }) : null
        ),
        c.detail ? el('div', { class: 'sub', text: c.detail }) : null
      )
    ));
  }
}

function renderDevices(hw) {
  const box = qs('#status-devices');
  if (!box) return;
  clear(box);
  if (!hw) { box.appendChild(el('div', { class: 'muted', text: '暂无设备信息' })); return; }
  const devices = (hw.devices || []);
  if (!devices.length) {
    box.appendChild(el('div', { class: 'muted', text: '未探测到加速设备（将使用 CPU 推理）' }));
  } else {
    for (const d of devices) box.appendChild(deviceCard(mapDevice(d)));
  }
  if (hw.profile && hw.profile.profile_id) {
    box.appendChild(el('div', { class: 'muted', style: { marginTop: '8px' }, text: '选用剖面：' + hw.profile.profile_id + (hw.profile.experimental ? '（实验性）' : '') }));
  }
  if (hw.warnings && hw.warnings.length) {
    box.appendChild(el('div', { class: 'muted', style: { marginTop: '4px' }, text: '⚠ ' + hw.warnings.join('；') }));
  }
}

function renderBackends(snap) {
  const box = qs('#status-backends');
  if (!box) return;
  clear(box);
  if (!snap || !snap.backends) { box.appendChild(el('div', { class: 'muted', text: '暂无后端信息' })); return; }
  const active = snap.active;
  const entries = Object.values(snap.backends);
  if (!entries.length) { box.appendChild(el('div', { class: 'muted', text: '无注册后端' })); return; }
  for (const b of entries) {
    const tags = [];
    if (b.name === active) tags.push(el('span', { class: 'tag ok', text: '活跃' }));
    tags.push(el('span', { class: b.healthy ? 'tag ok' : 'tag bad', text: b.healthy ? '健康' : '异常' }));
    box.appendChild(el('div', { class: 'model-row' },
      el('div', { class: 'info' },
        el('div', { class: 'row', style: { gap: '6px', alignItems: 'center' } },
          el('span', { class: 'name', text: b.name }),
          ...tags
        ),
        b.detail ? el('div', { class: 'sub', text: b.detail }) : null
      )
    ));
  }
  if (snap.chain && snap.chain.length) {
    box.appendChild(el('div', { class: 'muted', style: { marginTop: '6px' }, text: '降级链：' + snap.chain.join(' → ') }));
  }
}

async function refresh() {
  try { const r = await api.system(); store.set({ system: r }); } catch {}
  try { const r = await api.hardware(); store.set({ hardware: r }); } catch {}
  try { const r = await api.backends(); store.set({ backends: r }); } catch {}
  try { const r = await api.healthDeep(); store.set({ health: r }); } catch {}
}

async function restartOllama() {
  const btn = qs('#status-restart');
  if (btn) btn.disabled = true;
  try {
    await api.restartOllama();
    showToast('已请求重启 Ollama', 'ok');
    setTimeout(refresh, 1500);
  } catch (e) {
    showToast(await toUserError(e));
  } finally {
    if (btn) btn.disabled = false;
  }
}

export function init() {
  const root = qs('#view-status');
  clear(root);

  const sysBox = el('div', { id: 'status-system', class: 'kv-grid' });
  const healthBox = el('div', { id: 'status-health' });
  const devBox = el('div', { id: 'status-devices' });
  const beBox = el('div', { id: 'status-backends' });

  const refreshBtn = el('button', { class: 'btn sm', text: '刷新', on: { click: refresh } });
  const restartBtn = el('button', { id: 'status-restart', class: 'btn sm', text: '重启 Ollama', on: { click: restartOllama } });

  root.appendChild(el('div', {},
    el('div', { class: 'row', style: { justifyContent: 'space-between', alignItems: 'center' } },
      el('h2', { class: 'view-title', text: '系统状态' }),
      el('div', { class: 'row', style: { gap: '8px' } }, refreshBtn, restartBtn)
    ),
    el('div', { class: 'panel', style: { marginBottom: '16px' } },
      el('h3', { text: '系统信息' }), sysBox
    ),
    el('div', { class: 'panel', style: { marginBottom: '16px' } },
      el('h3', { text: '健康检查' }), healthBox
    ),
    el('div', { class: 'panel', style: { marginBottom: '16px' } },
      el('h3', { text: '设备' }), devBox
    ),
    el('div', { class: 'panel' },
      el('h3', { text: '推理后端' }), beBox
    )
  ));

  // 初次渲染（用 bootstrap 已拉取的数据）
  const s = store.get();
  renderSystem(s.system);
  renderHealth(s.health);
  renderDevices(s.hardware);
  renderBackends(s.backends);

  // 数据更新时同步刷新（仅渲染对应区块，避免整页重建）
  store.subscribe((st) => {
    renderSystem(st.system);
    renderHealth(st.health);
    renderDevices(st.hardware);
    renderBackends(st.backends);
  });
}
