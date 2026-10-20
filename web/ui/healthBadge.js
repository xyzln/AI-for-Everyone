// 健康徽章渲染（零依赖），复用 style.css 的 .badge / .badge.ok / .badge.bad
import { clear } from './dom.js';

// renderHealthBadge(container, healthOrCheck)
//  - healthOrCheck 可为：null（未知）、boolean、HealthReport（含 .healthy）、CheckResult（含 .ok）
//  - 会写 container.className = 'badge' | 'badge ok' | 'badge bad'
export function renderHealthBadge(container, healthOrCheck) {
  if (!container) return container;
  let ok = null;
  let label = '—';

  if (healthOrCheck == null) {
    ok = null; label = '—';
  } else if (typeof healthOrCheck === 'boolean') {
    ok = healthOrCheck; label = ok ? '健康' : '异常';
  } else if (typeof healthOrCheck === 'object') {
    if ('healthy' in healthOrCheck) {
      ok = !!healthOrCheck.healthy;
      label = ok ? '服务健康' : '服务异常';
    } else if ('ok' in healthOrCheck) {
      ok = !!healthOrCheck.ok;
      label = ok ? '正常' : '异常';
    }
  }

  const cls = ok == null ? 'badge' : (ok ? 'badge ok' : 'badge bad');
  container.className = cls;
  container.textContent = label;
  return container;
}
