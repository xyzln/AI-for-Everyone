// 设备卡片（零依赖），复用 style.css 的 .card / .panel / .muted
import { el } from './dom.js';
import { evidenceTag } from './evidenceTag.js';

// deviceCard(device) -> .card.panel
// device: { type, name, vram_gb?, evidence?|source?, detail?, caveats? }
export function deviceCard(device) {
  if (!device) {
    return el('div', { class: 'card panel muted', text: '未探测到设备信息' });
  }
  const d = device;
  const level = d.evidence != null ? d.evidence : d.source;

  const header = el('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' } },
    el('strong', { text: d.name || d.type || '设备' }),
    evidenceTag(level)
  );

  const parts = [];
  if (d.type) parts.push('类型：' + d.type);
  if (d.vram_gb != null) parts.push('显存：' + d.vram_gb + ' GB');
  if (d.detail) parts.push(d.detail);
  const sub = parts.length ? el('div', { class: 'muted', text: parts.join(' · '), style: { marginTop: '4px' } }) : null;

  const children = [header];
  if (sub) children.push(sub);
  if (d.caveats && d.caveats.length) {
    children.push(el('div', { class: 'muted', style: { marginTop: '4px' }, text: '注意：' + d.caveats.join('；') }));
  }
  return el('div', { class: 'card panel', style: { marginBottom: '8px' } }, ...children);
}
