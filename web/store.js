// 轻量 observable store（<100 行，零依赖）
export function createStore(initial = {}) {
  let state = initial;
  const listeners = new Set();
  return {
    get: () => state,
    set(patch) {
      const next = typeof patch === 'function' ? patch(state) : patch;
      state = { ...state, ...next };
      for (const fn of listeners) fn(state);
    },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  };
}

export const store = createStore({
  view: 'wizard',
  ws: 'connecting',
  system: null,
  hardware: null,
  health: null,
  backends: null,
  models: [],
  activeModel: null,
  chatOptions: { temperature: 0.7, top_p: 0.9, num_ctx: 4096, seed: null },
  setup: { runId: null, status: 'idle', steps: [], error: null },
  pull: null,
  chat: { messages: [], streaming: false },
});
