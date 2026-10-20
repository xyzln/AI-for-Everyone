// fetch 封装：统一错误体解析、toUserError、SSE 帧读取（零依赖）

export class UserError extends Error {
  constructor(code, title, detail, action, traceId) {
    super(title);
    this.code = code; this.title = title; this.detail = detail; this.action = action; this.traceId = traceId;
  }
}

const ERROR_TITLES = {
  VALIDATION: '请求内容没有通过校验',
  CONFIG_INVALID: '配置修改未通过校验',
  STEP_INVALID: '部署阶段参数不正确',
  MODEL_INVALID_NAME: '模型名称格式不正确',
  BACKEND_UNKNOWN: '选择了未知的推理后端',
  MODEL_NOT_FOUND: '本地没有安装该模型',
  SETUP_NOT_FOUND: '还没有运行过一键部署',
  ROUTE_NOT_FOUND: '接口不存在',
  PULL_IN_PROGRESS: '已有拉取任务在进行中',
  SETUP_RUNNING: '部署正在进行中',
  RATE_LIMITED: '请求太频繁了',
  INTERNAL_ERROR: '服务内部出错',
  OLLAMA_UNAVAILABLE: '连不上 Ollama',
  BACKEND_UNHEALTHY: '推理后端当前不可用',
  MODEL_NOT_LOADED: '模型尚未就绪',
  UPSTREAM_TIMEOUT: '模型响应超时',
};

// 解析统一错误体或网络错误为 UserError
export async function toUserError(resOrErr) {
  if (resOrErr instanceof UserError) return resOrErr;
  if (resOrErr instanceof TypeError) {
    return new UserError('NETWORK', '连不上 AIE 服务（127.0.0.1:8189）', '请确认 aife serve 正在运行', '重试');
  }
  if (resOrErr && resOrErr.json) {
    try {
      const body = await resOrErr.json();
      const e = body && body.error;
      if (e && e.code) {
        const detail = e.details ? formatDetails(e.code, e.details) : e.message;
        const action = actionFor(e.code);
        return new UserError(e.code, ERROR_TITLES[e.code] || e.message, detail, action, e.trace_id);
      }
    } catch (_) { /* ignore */ }
    return new UserError('HTTP_' + (resOrErr.status || ''), '请求失败（' + (resOrErr.status || '?') + '）', '', '重试');
  }
  return new UserError('UNKNOWN', '发生未知错误', String(resOrErr), '重试');
}

function formatDetails(code, d) {
  if (code === 'MODEL_NOT_FOUND' && d.installed) return '已安装：' + d.installed.join('、');
  if (code === 'MODEL_NOT_LOADED' && d.model) return '模型：' + d.model;
  if (code === 'PULL_IN_PROGRESS' && d.task_id) return '任务：' + d.task_id;
  if (code === 'SETUP_RUNNING' && d.current_step) return '当前阶段：' + d.current_step;
  return d.message || '';
}
function actionFor(code) {
  if (code === 'MODEL_NOT_FOUND' || code === 'MODEL_NOT_LOADED') return '去模型页';
  if (code === 'OLLAMA_UNAVAILABLE' || code === 'BACKEND_UNHEALTHY') return '去状态页';
  if (code === 'SETUP_NOT_FOUND') return '去向导页';
  return null;
}

async function request(method, path, body, opts = {}) {
  const init = { method, headers: {} };
  if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
  if (opts.signal) init.signal = opts.signal;
  const res = await fetch(path, init);
  if (!res.ok) { res._path = path; throw res; }
  if (res.status === 204) return null;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return await res.json();
  return res;
}

export const api = {
  health: () => request('GET', '/api/health'),
  system: () => request('GET', '/api/system'),
  hardware: () => request('GET', '/api/hardware'),
  healthDeep: () => request('GET', '/api/health/deep'),
  backends: () => request('GET', '/api/backends'),
  models: () => request('GET', '/api/models'),
  modelsAvailable: (profile) => request('GET', '/api/models/available' + (profile ? '?device_profile=' + encodeURIComponent(profile) : '')),
  pullModel: (name) => request('POST', '/api/models/pull', { name }),
  deleteModel: (name) => request('DELETE', '/api/models/' + encodeURIComponent(name)),
  setupStatus: () => request('GET', '/api/setup/status'),
  setupRun: (body) => request('POST', '/api/setup/run', body || {}),
  selectBackend: (name, force) => request('POST', '/api/backends/select', { name, force: !!force }),
  restartOllama: () => request('POST', '/api/ollama/restart'),
  chat: (body) => request('POST', '/api/chat', body),
  chatStream: (body, signal) => fetch('/api/chat/stream', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  }),
};

// SSE 读取器（零依赖）：解析 event:/data: 帧，逐事件回调
export async function readSSE(res, onEvent) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
      const ev = /(?:^|\n)event:\s*(.+)/.exec(frame)?.[1]?.trim() ?? 'message';
      const dataLine = /(?:^|\n)data:\s*(.+)/.exec(frame)?.[1];
      let data = null;
      if (dataLine) { try { data = JSON.parse(dataLine); } catch { data = dataLine; } }
      onEvent({ event: ev, data });
    }
  }
}
