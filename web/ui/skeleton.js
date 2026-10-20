// 骨架屏（零依赖），复用 style.css 的 .skeleton
import { el } from './dom.js';

// skeleton(lines=3) -> 包含 N 条 .skeleton 的容器
export function skeleton(lines = 3) {
  const wrap = el('div', {});
  for (let i = 0; i < lines; i++) {
    wrap.appendChild(el('div', { class: 'skeleton' }));
  }
  return wrap;
}
