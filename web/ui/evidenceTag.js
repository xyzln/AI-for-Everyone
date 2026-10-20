// 证据等级标签（零依赖），复用 style.css 的 .ev.E0..E3
// ADR-007：E0 实测 / E1 工具输出 / E2 推断 / E3 猜测
const INFO = {
  E0: 'E0 · 实测：由硬件接口或系统 API 直接读取，可信度最高',
  E1: 'E1 · 工具输出：由探测工具（如 nvidia-smi）的输出解析得到',
  E2: 'E2 · 推断：基于已知信息推断得出',
  E3: 'E3 · 猜测：低置信度猜测，仅供参考',
};

const LEVELS = ['E0', 'E1', 'E2', 'E3'];

// evidenceTag(level) -> span.ev.<LEVEL>，带 title 释义
export function evidenceTag(level) {
  const raw = String(level || 'E2').toUpperCase();
  const lvl = LEVELS.includes(raw) ? raw : 'E2';
  const tag = document.createElement('span');
  tag.className = 'ev ' + lvl;
  tag.textContent = lvl;
  tag.title = INFO[lvl];
  return tag;
}
