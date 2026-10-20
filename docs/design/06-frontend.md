# AIE 前端体验设计 v1.0（零构建原生 ESM 单页）

- 版本：v1.0-draft（含 15 项【待确认】，交回主理人）
- 作者：前端体验工程师 颜可心
- 读者：主理人（高屋建）、程不宕（服务/契约）、凌无缺（测试验收）、实现组
- 落盘路径：docs/design/06-frontend.md

## 0. 设计依据与总纲

| 输入 | 引用条目 | 落点 |
|------|---------|------|
| 需求定义 | US1.1–1.3（一键部署/分阶段重试/前置检查）、US4.1–4.4（模型）、US5.1–5.4（对话/流式/中断/回退）、US6.1–6.4（体检/修复建议）、D4（默认 qwen2.5:3b）、D5（端口 8189） | 全文 |
| 架构设计 | §2 目录 web/ 蓝本、§5.1 统一错误规范、§5.2 REST 路由表、§5.3 WS 事件契约、§6 非功能性目标、ADR-004（零构建原生 ESM）、ADR-007（证据等级 UI 化）、D8（模型分档）、D10（仅 127.0.0.1）、D14（v1 仅简体中文浅色主题）、D16（不做遥测埋点） | 全文 |
| Octop 先行实现 | web/index.html、web/app.js、web/styles.css（浅色令牌、WS 断线重连、零构建工程范式） | §3 组件、§7 令牌 |

**总纲（五条原则）**：

1. **零依赖离线**：无 npm、无打包器、无框架、无 CDN、无 webfont；`file://` 直开不支持，必须经 `aife serve`（127.0.0.1:8189）静态托管（架构既定）。
2. **失败可解释**（US1.2/US6.3）：任何失败必须同时回答「卡在哪一步、为什么、怎么修」，修复命令一键复制；禁止只弹一句「出错了」。
3. **流式可控**（US5.3）：SSE 逐字渲染、随时可停止（已接收内容保留）、`error` 事件统一错误体呈现、网络层错误自动降级非流式重试一次。
4. **证据诚实**（US2.2/ADR-007）：硬件结论一律带 E0–E3 证据等级标签，无标记视为缺陷；CPU 回退给性能预期提示（US2.3）。
5. **浅色中文**（D14）：v1 仅简体中文、仅浅色主题；文案集中在页面级文案对象，为演进留缝。

---

## 1. 信息架构

### 1.1 导航结构

单页四视图，顶部 tab 导航（WAI-ARIA tabs 模式）+ hash 路由，刷新后保持当前视图：

```
┌────────────────────────────────────────────────────────────────┐
│ ◈ AI For everyone   [部署向导][聊天][模型][状态]   ●WS ●健康 v0.1.0 │
├────────────────────────────────────────────────────────────────┤
│  <main> 当前 tab 对应的视图（tabpanel，按需动态 import）          │
└────────────────────────────────────────────────────────────────┘
```

| 元素 | 行为 |
|------|------|
| 顶部 tab | `role="tablist"`，四个 tab：部署向导 / 聊天 / 模型 / 状态；支持 ←→ 方向键切换；点击写 `location.hash` |
| hash 路由 | `#/wizard`、`#/chat`、`#/models`、`#/status`；`hashchange` → 卸载旧视图模块、动态 `import()` 新视图模块并 mount |
| 右侧状态区 | WS 连接灯（connecting/open/closed 三态 title 含原因）、服务健康徽章（来自 `/api/health/deep` 的 healthy）、版本号（来自 `/api/system`） |
| 全局挂载点 | toast 容器、modal 容器（`index.html` 预留 `<div id="toast-root">`、`<div id="modal-root">`） |

**首次进入路由决策**（app.js 启动序列）：

```
GET /api/health（<300ms 探活）
  ├─ fetch 失败 → 全屏「服务未连接」错误态（见 §1.3-E5），不进任何视图
  └─ 200 →
      GET /api/setup/status
        ├─ 200 且历史 run 成功过 → 默认 #/chat
        ├─ 200 且 status=running   → #/wizard（接管进行中的部署）
        └─ 404 SETUP_NOT_FOUND     → #/wizard（强制引导，对应 US1.1 场景 A）
      同时 connectEvents() 建立 WS；GET /api/system 填充顶栏版本与后端名
```

聊天视图在「无模型」时不是死胡同：显示空态引导去模型页拉取，而不是禁用输入（详见 §2.3）。

### 1.2 每视图「首屏必须回答的问题」

| 视图 | 首屏必须回答的问题 | 回答该问题的区块 |
|------|------------------|-----------------|
| 部署向导 | 我的机器现在到哪一步了？卡住没有？卡住的话**为什么、怎么修**？已跑完没有？ | 步骤时间线 + 当前步骤进度 + 失败修复卡片 + 部署日志 |
| 聊天 | 我在跟哪个模型说话？它刚才回什么了？我随时能打断吗？这个后端现在能聊吗？ | 模型选择器 + 消息流（流式光标）+ 停止按钮 + 后端错误条 |
| 模型 | 我装了什么模型（多大/什么量化）？我的机器适合装什么？拉取/删除正在发生吗？ | 已装列表 + 推荐目录（按剖面）+ 拉取任务进度条 |
| 状态 | 我的机器在用什么算力、**证据等级是什么**？后端健康吗？模型就绪吗？磁盘够吗？ | 硬件剖面卡 + 设备清单（E0–E3 标签）+ 深度健康检查列表 + 后端切换 |

### 1.3 五态设计总纲（本地单用户产品的落地映射）

AIE 是本地单用户产品，无账号体系（需求 §3.4 多租户鉴权 Won't have），传统「无权限态」不存在，**落地为三类「不可用态」**，与通用四态合并为每视图必覆的五态：

| 状态 | 通用语义 | AIE 落地补充 |
|------|---------|-------------|
| 正常态 | 数据齐备，主流程可见 | — |
| 空态 | 无数据时的引导（无模型/无部署记录/无会话） | 空态必须带下一步动作（按钮），不是一句「暂无数据」 |
| 加载态 | 首屏骨架 + 局部 loading | 骨架屏（skeleton）；区块间加载互不阻塞 |
| 错误态 | 契约错误码 → 用户可读文案 + 重试 | 文案映射见 §5.2；**禁止 `alert()`**（Octop 教训），统一 toast/modal |
| 不可用态（原「无权限态」） | — | **E5 服务未连接**：`/api/health` fetch 失败 → 全屏错误态「连不上 AIE 服务（127.0.0.1:8189），请确认 `aife serve` 正在运行」+ 重试按钮；**E6 后端不健康**：503 BACKEND_UNHEALTHY / MODEL_NOT_LOADED → 功能禁用 + 原因 + 修复入口；**E7 配置未完成**：setup 从未运行 → 聊天/模型视图显示引导而非报错 |

每视图的五态明细见 §2 各节表格。全局兜底：`window.addEventListener('error')` 与 `unhandledrejection` → toast 展示 + `console.error`（**无任何数据外发**，D16）。

---

## 2. 页面清单与线框描述

### 2.1 页面地图

| 页面 | 路由 | 职责 | 访问权限 | 来源用户故事 |
|------|------|------|---------|-------------|
| 部署向导 | `#/wizard` | 触发 setup 流水线、WS 进度展示、失败修复指引、完成后跳转聊天 | 本地 127.0.0.1 可达即可用（无鉴权，D10） | US1.1、US1.2、US1.3、US6.3 |
| 聊天 | `#/chat` | OpenAI 兼容对话、SSE 流式渲染、停止/中断、模型切换、参数面板 | 同上 | US5.1、US5.2、US5.3、US5.4 |
| 模型管理 | `#/models` | 已装列表、推荐目录（按硬件剖面）、拉取进度、删除确认 | 同上 | US4.1、US4.2、US4.3、US4.4 |
| 状态 | `#/status` | 硬件剖面与证据等级、深度健康检查、后端切换、Ollama 重启 | 同上 | US2.1、US2.2、US2.3、US6.1、US5.4、US6.4 |

> 「访问权限」列如实反映 MVP：默认仅 127.0.0.1（D10），无 token 鉴权；用户自行改 `server.host=0.0.0.0` 的风险由 README 提示（架构【待确认】#4 已裁决 MVP 不做鉴权），前端不做额外拦截。

### 2.2 部署向导 `#/wizard`

**布局骨架（≥1024px 两栏；<1024px 单栏，日志折叠为 `<details>`）**：

```
┌──────────────────────────────────────────────────────────────────┐
│ 部署向导                                    [重新部署] [跳过重跑]  │
├───────────────────────────────────────┬──────────────────────────┤
│ ① 前置检查                             │ 部署日志                  │
│   ✔ Python 3.12.3                     │ [12:01:02] deps 检查开始  │
│   ✔ 内存 95.5GB（≥8GB）                │ [12:01:02] 硬件探测完成   │
│   ✔ 磁盘余量 85GB（≥20GB）             │   → CPU 剖面（证据 E1）   │
│ ② 硬件探测 → CPU 剖面 [E1]             │ [12:01:05] 安装 Ollama…  │
│   ⚠ 当前为 CPU 推理，首 token 约 10s 量级│ [12:03:11] Ollama 就绪  │
│ ③ 安装并配置 Ollama         ✔ 2m08s   │ [12:03:12] 拉取模型…      │
│ ④ 拉取模型 qwen2.5:3b   ▓▓▓░░░ 62%    │   → 1.2GB / 1.9GB        │
│ ⑤ 推理验证               ○ 等待中      │                          │
│ ⑥ 启动服务               ○ 等待中      │                          │
│                                       │                          │
│ [开始一键部署]                         │                          │
├───────────────────────────────────────┴──────────────────────────┤
│ ⚠ 失败卡片（仅 setup.error 时展开，见下）                          │
└──────────────────────────────────────────────────────────────────┘
```

**核心交互流程**：

```
进入 #/wizard
  → GET /api/setup/status
      ├─ 404 → 渲染「首跑引导」：前置条件预览（来自 /api/system 的 platform/python）
      │        + [开始一键部署] 主按钮 + 说明文案（全程无需人工决策，US1.1）
      └─ 200 → 按 steps[] 渲染时间线；status=running 则接管（禁重复触发）
点 [开始一键部署]
  → POST /api/setup/run {} → 202 {run_id, status}
  → WS 事件驱动（见 §4.2）：setup.started → 时间线激活
      setup.step_progress → 当前步骤卡副标题（message）+ 日志追加
      setup.step_done     → 步骤打勾 + 耗时（duration_ms）
      model.pull_progress → ④ 步骤卡内进度条（completed/total 字节）
失败（setup.error {run_id, step, code, message, remedy}）
  → 失败卡片展开（见下）；该步骤标红；后续步骤置灰
  → [重试本阶段]：POST /api/setup/run {skip: 已完成阶段}（US1.2 断点续跑语义）
  → [重新部署]：POST /api/setup/run {}（全量，需 confirmModal 二次确认）
全部步骤 done
  → toast「部署完成」+ 1.5s 后自动 location.hash = '#/chat'
```

**失败修复卡片（US1.2 / US6.3 的界面落点，硬性要求）**：

```
┌───────────────────────────────────────────────────────────┐
│ ✘ 第 ④ 步「拉取模型」失败                        [收起]   │
│ 原因：拉取 qwen2.5:3b 时网络中断（code: OLLAMA_UNAVAILABLE）│
│ 怎么修（可复制执行）：                                       │
│   $ aife setup --skip-deps --skip-ollama        [复制]     │
│   $ aife doctor                               [复制]      │
│ 说明：已完成阶段不会重复执行；国内网络可配置镜像源后重试。    │
│ [重试本阶段]  [重新部署]  [查看完整日志]                    │
└───────────────────────────────────────────────────────────┘
```

卡片三要素缺一不可：**卡在哪一步**（步骤名+序号）、**为什么**（code+message）、**怎么修**（remedy.commands 逐条一键复制）。remedy 结构以后端契约为准（见 §6-X3）。

**五态**：

| 状态 | 触发条件 | 界面表现 |
|------|---------|---------|
| 正常 | setup running / 已完成 | 时间线 + 进度 + 日志实时追加 |
| 空 | 404 SETUP_NOT_FOUND（从未部署） | 首跑引导卡：前置条件预览 + [开始一键部署] |
| 加载 | 进入时 GET status/system；步骤执行中 | 骨架屏；当前步骤卡转圈 + step_progress.message |
| 错误 | setup.error；网络层 fetch 失败 | 失败修复卡片（如上）；网络错误用 errorState + 重试 |
| 不可用 | WS 断开；aife 服务整体不可达 | 步骤卡显示「进度更新暂停，正在重连…」+ 顶栏 WS 灯；服务不可达走全局 E5 全屏错误态 |

### 2.3 聊天 `#/chat`

**布局骨架（消息流居中 max-width 860px，输入栏 sticky 底部）**：

```
┌──────────────────────────────────────────────────────────────────┐
│ 模型 [qwen2.5:3b ▾]  后端 ollama ●  温度 [0.7]  [参数面板 ▾]      │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─ 你 ────────────────────────┐                                │
│   │ 你好，请用一句话介绍你自己     │                                │
│   └─────────────────────────────┘                                │
│   ┌─ AI（qwen2.5:3b）─────────────┐  ← 流式中：光标闪烁 aria-busy │
│   │ 你好！我是一个运行在你本机的大 ▌│                                │
│   │ 语言模型…                      │                                │
│   └─────────────────────────────┘                                │
|   ↑ 停止生成后：气泡脚注「已中断 · 保留已生成内容」                  │
|                                                                  |
|   ↑ 完成后：脚注「38 tokens · 2.1s」（usage 事件）                 │
├──────────────────────────────────────────────────────────────────┤
│ [输入消息，Enter 发送 / Shift+Enter 换行        ] [发送] [■ 停止] │
└──────────────────────────────────────────────────────────────────┘
```

**核心交互流程**：

```
发送（Enter 或 [发送]）
  → store.chat.messages 追加 user 消息 → UI 立即渲染（乐观）
  → POST /api/chat/stream {model, messages, options}（signal=AbortController）
  → SSE 事件（见 §4.3）：delta → appendDelta；usage/done → finalize；error → fail
[■ 停止]（生成中可见，Esc 亦可）
  → controller.abort() → reader 取消 → 气泡标记「已中断」，内容保留（US5.3）
网络层错误（fetch throw，非 AbortError）
  → 自动降级：POST /api/chat 非流式重试一次（US5.3）；仍失败 → 错误条
error 事件（应用层错误，如 BACKEND_UNHEALTHY）
  → 不降级，直接 fail(toUserError(error)) → 气泡位变错误态 + 修复按钮
模型切换（picker）
  → 仅改后续消息的 model，不清空历史；picker 数据来自 GET /api/models
参数面板（temperature / top_p / num_ctx / seed，白名单见 §6-X9）
  → 仅本页会话有效，写入请求 options；刷新不保留（v1 不持久化）
```

**五态**：

| 状态 | 触发条件 | 界面表现 |
|------|---------|---------|
| 正常 | 有模型可聊 | 消息流 + 输入栏；流式中显示停止按钮 |
| 空 | 无历史消息 | 欢迎语 + 3 个示例问题 chip（点击即发送） |
| 空（无模型） | `/api/models` 返回空 | 引导卡「还没有模型」+ [去模型页拉取 qwen2.5:3b]（E7 配置未完成落地） |
| 加载 | SSE 流式中；模型列表加载 | 流式气泡 + 闪烁光标；picker 禁用 + skeleton |
| 错误 | error 事件 / 非流式降级也失败 | 输入栏上方错误条（可读文案 + 修复按钮）；最后一条气泡标错误态可重试 |
| 不可用 | 503 BACKEND_UNHEALTHY / MODEL_NOT_LOADED | 输入框禁用 + 原因 + [去状态页体检] / [去模型页拉取]（E6） |

> 聊天走 SSE 独立通道，**不依赖 WS**：WS 断开不影响正在进行的对话（顶栏灯变化即可）。

### 2.4 模型管理 `#/models`

**布局骨架（≥1024px 两栏；<640px 单栏堆叠）**：

```
┌──────────────────────────────────────────────────────────────────┐
│ 模型管理                                              [+ 拉取模型] │
├───────────────────────────────┬──────────────────────────────────┤
│ 已安装（2）                    │ 推荐目录（按本机 CPU 剖面，US4.4）  │
│ ┌───────────────────────────┐ │ ┌──────────────────────────────┐ │
│ │ qwen2.5:3b        1.9GB   │ │ │ qwen2.5:1.5b   0.9GB  [拉取] │ │
│ │ 参数量 3B · Q4_K_M · 默认  │ │ │ 适合 8GB 内存                 │ │
│ │ [设为默认] [删除]          │ │ ├──────────────────────────────┤ │
│ ├───────────────────────────┤ │ │ qwen2.5:7b     4.4GB  [拉取] │ │
│ │ qwen2.5:1.5b      0.9GB   │ │ │ 需 16GB 内存（本机 95.5GB ✓） │ │
│ │ 参数量 1.5B · Q4_K_M       │ │ └──────────────────────────────┘ │
│ │ [设为默认] [删除]          │ │ 目录来自 GET /api/models/available│
│ └───────────────────────────┘ │ ?device_profile=cpu              │
├───────────────────────────────┴──────────────────────────────────┤
│ 拉取任务：qwen2.5:7b ▓▓▓▓▓░░░░ 47%  1.2GB / 2.6GB  verifying…    │
└──────────────────────────────────────────────────────────────────┘
```

**核心交互流程**：

```
进入 → GET /api/models + GET /api/models/available?device_profile=<来自 /api/hardware>
[拉取]（推荐目录或 [+ 拉取模型] 输入名称）
  → POST /api/models/pull {name} → 202 {task_id}
  → WS model.pull_progress → 底部任务条进度（字节级）
  → model.pull_done → 任务条消失 + 已装列表刷新 + toast「qwen2.5:7b 拉取完成」
  → 409 PULL_IN_PROGRESS → toast「已有拉取任务在进行中」
[删除]
  → confirmModal「删除模型 qwen2.5:1.5b？文件将从本机移除，需重新下载。」（危险样式）
  → 确认 → DELETE /api/models/qwen2.5%3A1.5b（name 需 encodeURIComponent）
  → 404 MODEL_NOT_FOUND（竞态）→ toast「模型已不存在」并刷新列表
[设为默认] → PATCH /api/config（v1 可不做该按钮，见 §6-X14）
```

**五态**：

| 状态 | 触发条件 | 界面表现 |
|------|---------|---------|
| 正常 | 有已装模型 | 列表 + 推荐目录；默认模型带「默认」标 |
| 空 | `/api/models` 为空 | 空态「还没有安装任何模型」+ [拉取默认模型 qwen2.5:3b] |
| 加载 | 首屏；目录加载 | skeleton；推荐卡片逐个 loading |
| 错误 | 503 OLLAMA_UNAVAILABLE | errorState「连不上 Ollama」+ [去状态页重启]；404 → toast |
| 不可用 | 拉取任务进行中 | 删除按钮禁用 + 任务条常驻显示进度（PULL_IN_PROGRESS 的 409 也汇聚到这里） |

### 2.5 状态 `#/status`

**布局骨架（≥1024px 两栏；<1024px 堆叠）**：

```
┌──────────────────────────────────────────────────────────────────┐
│ 状态                          [重新检查] [重启 Ollama] [刷新]      │
├───────────────────────────────┬──────────────────────────────────┤
│ 硬件剖面（US2.1/2.3）          │ 深度健康检查（US6.1/6.4）          │
│ ┌───────────────────────────┐ │ ✔ aife 服务   v0.1.0 · 运行 12m   │
│ │  CPU   证据 [E1]           │ │ ✔ Ollama     v0.5.7 · :11434     │
│ │  20 核 / 95.5GB RAM        │ │ ✔ 模型       qwen2.5:3b 已就绪   │
│ │  加速路径：CPU 回退         │ │ ✔ 后端       ollama              │
│ └───────────────────────────┘ │ ✘ 磁盘       余量 18GB（<20GB）   │
│ ⚠ 当前为 CPU 推理，首 token 约 │ │   → 建议：清理磁盘或迁移模型目录  │
│   10s 量级；无可用 GPU/NPU     │ │ 后端：[ollama ▾] [切换]          │
│ 设备清单                       │ │ 健康结论随 health.changed 实时更新│
│ ▸ Intel Core Ultra 7 265K [E1]│ │                                  │
│ ▸ 无 CUDA 设备          [E0]  │ │                                  │
│ ▸ NPU：无主线后端（实验性）[E3]│ │                                  │
└───────────────────────────────┴──────────────────────────────────┘
```

**核心交互流程**：

```
进入 → 并行 GET /api/system、/api/hardware、/api/health/deep、/api/backends
[重新检查] → 重新拉取四项（各自独立 loading，不互相阻塞）
[重启 Ollama] → confirmModal → POST /api/ollama/restart → toast + 刷新全部
[切换后端] → POST /api/backends/select {name}
  → 200 → picker 更新 + toast；503 BACKEND_UNHEALTHY → 可读文案 + [强制切换 force=true] 二次确认
WS health.changed → 顶栏健康徽章 + 健康列表局部刷新（无需整页重拉）
轮询兜底 → 每 15s GET /api/health/deep（WS 事件之外的补偿，见 §6-X16）
```

**五态**：

| 状态 | 触发条件 | 界面表现 |
|------|---------|---------|
| 正常 | 四项数据齐备 | 剖面 + 证据标签 + 健康列表 + 后端 picker |
| 空 | `/api/hardware` devices 为空（极端） | 「未探测到设备信息」+ [重新检查] |
| 加载 | 进入/重新检查 | 各卡片独立 skeleton |
| 错误 | `/api/system` 503 OLLAMA_UNAVAILABLE | 卡片级错误 + [重启 Ollama]；`/api/health/deep` 恒 200，fail 项进 checks 红叉 + remedy |
| 不可用 | aife 服务整体不可达 | 全局 E5 全屏错误态（fetch 失败） |

---

## 3. 组件体系（原生 ESM 模块划分）

### 3.1 web/ 文件职责（在架构 §2 蓝本上细化）

```
web/
├── index.html            # 单页外壳：顶栏（brand/tablist/状态区）+ 四个 tabpanel 容器
│                         #   + #toast-root/#modal-root 挂载点 + <script type="module" src="./app.js">
├── app.js                # ESM 入口：hash 路由、store 装配、WS 连接、视图动态 import/mount/unmount、
│                         #   启动序列（§1.1）、全局错误边界、15s 轮询编排
├── api.js                # fetch 封装：统一错误体解析（§5.1 schema）、toUserError 文案映射（§5.2）、
│                         #   SSE 帧读取器 readSSE、网络错误识别
├── store.js              # 轻量 observable store（<100 行，见 §4.1）
├── ws.js                 # /ws/events 连接管理：指数退避重连、45s 无帧判定掉线、事件分发、状态回调
├── style.css             # 设计令牌（§7）+ 组件样式；无 CSS 框架、无 @import 外链
├── pages/
│   ├── wizard.js         # 部署向导：步骤时间线、失败修复卡片、日志面板、setup 触发与重试
│   ├── chat.js           # 聊天：消息流、streamRenderer 装配、AbortController、模型 picker、参数面板
│   ├── models.js         # 模型管理：已装列表、推荐目录、拉取任务条、删除确认
│   └── status.js         # 状态：剖面卡、设备清单、健康列表、后端切换、Ollama 重启
├── ui/
│   ├── dom.js            # $ / $$ / h（hyperscript）最小 DOM 工具
│   ├── toast.js          # 全局轻提示（info/ok/warn/error，可带 traceId）
│   ├── modal.js          # confirmModal（Promise<boolean>），禁用原生 confirm()
│   ├── progressBar.js    # 确定性（字节/百分比）与不确定性（indeterminate）进度条
│   ├── streamRenderer.js # 流式消息渲染器：rAF 批量刷新、滚动锚定、中断/失败/收尾状态机
│   ├── healthBadge.js    # 健康徽章（ok=null 表示未知/加载中）
│   ├── evidenceTag.js    # E0–E3 证据等级标签（title 释义）
│   ├── deviceCard.js     # 设备卡片（类型/名称/显存/证据/caveats）
│   ├── emptyState.js     # 空态（标题 + 提示 + 动作按钮）
│   ├── errorState.js     # 错误态（UserError → 可读文案 + 重试/修复动作）
│   └── skeleton.js       # 加载骨架
└── mock/
    └── mockHandlers.js   # 【仅开发态】fetch 拦截 mock；分发打包时由 scripts/build-release.sh
                          #   排除（与架构 §2 打包目录约定联动，见 §6-X17）
```

> 架构 §2 的 web/ 蓝本（index.html / app.js / api.js / style.css / pages×4）保持不变；本方案新增的 store.js、ws.js、ui/、mock/ 属前端内部模块细化，**不改动任何接口契约**。若主理人要求架构文档同步回写该目录树，见 §6-X17。

**工程红线（写入各文件头注释）**：① 禁 `alert()/confirm()/prompt()`（统一 toast/modal）；② 所有外部数据（模型输出、错误 message、日志）一律 `textContent`/`setAttribute` 赋值，**禁止 innerHTML 拼接不可信文本**（防 XSS——模型输出与后端 message 均视为不可信）；③ 禁任何 `http(s)://` 外部域运行时请求；④ 不用 `eval`/`new Function`。

### 3.2 复用组件清单（接口草案，函数签名级）

| 组件 | 层级 | 职责 | Props / 签名 | 复用场景 |
|------|------|------|------------|---------|
| `h` | 原子 | 创建元素 | `h(tag, attrs?, ...children) → HTMLElement`；attrs 支持 `class/dataset/value/on*(fn)/aria-*/role` | 全部视图 |
| `toast` | 原子 | 轻提示 | `toast(message, {type='info', duration=4000, traceId}) → void` | 全局（拉取完成/复制成功/切换后端/错误兜底） |
| `confirmModal` | 原子 | 危险操作二次确认 | `confirmModal({title, body, confirmText?, cancelText?, danger?}) → Promise<boolean>` | 删除模型/重启 Ollama/强制切换后端/重新部署 |
| `createProgressBar` | 分子 | 进度条 | `createProgressBar(container) → {setRatio(p01), setLabel(text), setIndeterminate(on), destroy()}` | 模型拉取、向导步骤内进度 |
| `healthBadge` | 原子 | 健康徽章 | `healthBadge(ok, label, detail?) → HTMLElement`；`ok=null` 未知态 | 顶栏、状态页健康项 |
| `evidenceTag` | 原子 | 证据等级标签 | `evidenceTag(level: 'E0'\|'E1'\|'E2'\|'E3') → HTMLElement` | 状态页剖面与设备清单 |
| `deviceCard` | 分子 | 设备卡片 | `deviceCard(device: {type,name,vram_gb?,source,caveats?}) → HTMLElement` | 状态页设备清单 |
| `emptyState` | 分子 | 空态 | `emptyState({title, hint?, action?}) → HTMLElement` | 四视图空态 |
| `errorState` | 分子 | 错误态 | `errorState(userError: UserError, {onRetry?}) → HTMLElement` | 四视图错误态 |
| `skeleton` | 原子 | 骨架屏 | `skeleton(rows=3) → HTMLElement` | 四视图加载态 |
| `createStreamRenderer` | 组织 | 流式消息渲染 | `createStreamRenderer({container}) → {start, appendDelta(text), setUsage(u), finalize(data?), fail(userError), interrupt(), reset()}` | 聊天 |
| `connectEvents` | 组织（非 UI） | WS 生命周期 | `connectEvents({onEvent, onStatus}) → {close()}`；退避 1s→8s 封顶；45s 无帧判掉线 | app.js 全局单例 |

**streamRenderer 状态机（内部）**：`idle → streaming → (finalized | interrupted | failed)`；`interrupt()` 后气泡脚注「已中断 · 保留已生成内容」；`fail()` 后气泡变错误态并挂重试按钮；滚动锚定：用户上滚超过 80px 停止自动贴底并显示「回到底部」 pill。

### 3.3 页面私有组件

| 页面 | 私有组件 | 签名要点 |
|------|---------|---------|
| wizard | `stepTimeline(steps)` | `steps: [{name,label,status,started_at?,finished_at?,duration_ms?,message?,error?}]` |
| wizard | `remedyCard(error)` | `error: {step, code, message, remedy:{summary, commands[]}}`；commands 逐行 [复制] 按钮 |
| chat | `messageBubble({role, text, state})` | `state: 'done'\|'streaming'\|'interrupted'\|'failed'` |
| chat | `modelPicker(models, active, onChange)` | 原生 `<select>`，Ollama 不可用时禁用 |
| chat | `paramsPanel(options, onChange)` | temperature/top_p/num_ctx/seed（白名单见 §6-X9） |
| models | `modelRow(model, {isDefault, onDelete})` | `model: {name,size,family,parameter_size,quantization,modified_at}` |
| models | `catalogCard(entry, onPull)` | `entry: {name,size_gb,min_ram_gb,tags,recommended_for}` |
| models | `pullTaskBar(task)` | `task: {task_id, model, completed, total, status}` |
| status | `healthCheckList(checks)` | `checks: {aife?,ollama?,models?,backend?,disk?}`（子项 schema 见 §6-X6） |
| status | `backendPicker(backends, onSelect)` | `backends: {active, chain[], health{}}` |

---

## 4. 状态管理

### 4.1 轻量 store（observable，<100 行）

```js
// web/store.js —— 全部代码 <100 行；禁引入任何依赖
export function createStore(initial = {}) {
  let state = initial;
  const listeners = new Set();
  return {
    get: () => state,
    set(patch) {
      const next = typeof patch === 'function' ? patch(state) : patch;
      state = { ...state, ...next };           // 浅合并；嵌套对象由调用方整体替换
      for (const fn of listeners) fn(state);
    },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  };
}
```

全局状态形状（app.js 装配一份，各视图订阅自己关心的切片）：

```js
{
  view: 'wizard' | 'chat' | 'models' | 'status',   // hash 路由驱动
  ws: 'connecting' | 'open' | 'closed',            // ws.js 状态回调写入
  system: null,          // /api/system：{version, platform, python, ollama_version, profile, active_backend}
  hardware: null,        // /api/hardware：HardwareReport
  health: null,          // /api/health/deep：HealthReport
  backends: null,        // /api/backends：{active, chain[], health{}}
  models: [],            // /api/models：ModelInfo[]
  activeModel: null,     // 聊天 picker 当前值（默认 config/models.default 或首个已装）
  chatOptions: { temperature: 0.7, top_p: 0.9, num_ctx: 4096, seed: null },
  setup: { runId: null, status: 'idle'|'running'|'done'|'failed', steps: [], error: null },
  pull: null,            // {task_id, model, completed, total, status}
  chat: { messages: [], streaming: false },        // messages: [{role, text, state, usage?}]
  toasts: []             // toast.js 自管（或走独立微 store）
}
```

订阅约定：视图 mount 时 `store.subscribe(render)` 并保存退订函数，unmount 时调用（防定时器/监听泄漏）；禁止视图间直接互调，只经 store + WS 事件。

### 4.2 WS 事件订阅表（架构 §5.3 → UI 更新映射）

单连接 `/ws/events` 由 app.js 持有、全局广播分发；下表为**唯一权威的事件→UI 映射**：

| 事件（§5.3） | payload 要点 | store 变更 | UI 更新 |
|-------------|-------------|-----------|---------|
| `setup.started` | `{run_id, steps[]}` | `setup={runId, status:'running', steps}` | 向导时间线激活；禁「开始」按钮 |
| `setup.step_progress` | `{run_id, step, message}` | `steps[i].message` | 当前步骤卡副标题；日志面板追加 |
| `setup.step_done` | `{run_id, step, duration_ms}` | `steps[i].status='done', duration_ms` | 步骤打勾 + 耗时；推进到下一步 |
| `setup.error` | `{run_id, step, code, message, remedy}` | `setup.status='failed', setup.error` | **失败修复卡片**（卡点/原因/可复制修复命令/重试按钮） |
| `model.pull_progress` | `{task_id, status, completed, total}` | `pull={...}` | 模型页任务条进度（字节）；向导④步骤内嵌进度条 |
| `model.pull_done` | `{task_id, model}` | `pull=null` | 任务条消失；刷新 `/api/models`；toast「拉取完成」 |
| `log.line` | `{level, logger, message, ts}` | —（不入 store） | 向导日志面板追加（仅 wizard 激活时渲染；见 §6-X15） |
| `backend.changed` | `{active, reason}` | `backends.active`；`system.active_backend` | 顶栏后端名；状态页 picker；toast「已切换到 {active}（{reason}）」 |
| `health.changed` | `{healthy, failed_checks[]}` | `health`（可仅补 failed 项） | 顶栏健康徽章；状态页红叉项 + remedy |
| `error` | 统一 error 体（§5.1） | — | 全局 toast（带 code 与 trace_id） |
| `heartbeat` | `{}`（30s） | — | ws.js 内部刷新 lastBeat（探活，无 UI） |

### 4.3 SSE 读取与中断处理（AbortController）

```js
// web/api.js —— SSE 帧读取（零依赖；协议：event: <name>\ndata: <json>\n\n）
export async function readSSE(res, onEvent) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();       // signal abort 时此处 reject
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
      const evName = /(?:^|\n)event:\s*(.+)/.exec(frame)?.[1]?.trim() ?? 'message';
      const dataLine = /(?:^|\n)data:\s*(.+)/.exec(frame)?.[1];
      let data = null;
      try { data = dataLine ? JSON.parse(dataLine) : null; } catch { data = dataLine; }
      onEvent({ event: evName, data });
    }
  }
}

// web/pages/chat.js —— 关键结构（发送/停止/降级）
let controller = null;
async function send(text) {
  controller = new AbortController();
  const r = createStreamRenderer({ container });
  r.start();
  store.set((s) => ({ chat: { ...s.chat, streaming: true, messages: [...s.chat.messages, { role: 'user', text }] } }));
  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: store.get().activeModel, messages: toApiMessages(), options: store.get().chatOptions }),
      signal: controller.signal,
    });
    if (!res.ok) throw await apiErrorFrom(res);          // 预检失败：解析统一错误体
    await readSSE(res, (ev) => {
      if (ev.event === 'delta') r.appendDelta(ev.data?.text ?? '');
      else if (ev.event === 'usage') r.setUsage(ev.data);
      else if (ev.event === 'done') r.finalize(ev.data);
      else if (ev.event === 'error') r.fail(toUserError(ev.data));   // 统一 error 体，不降级
    });
    if (!r.settled) r.finalize();                        // 流结束但未收到 done：兜底收尾
  } catch (err) {
    if (err.name === 'AbortError') { r.interrupt(); return; }        // 用户点停止：保留内容
    if (isNetworkError(err) && !retriedOnce) { retriedOnce = true; return sendNonStreamFallback(text, r); }
    r.fail(toUserError(err));
  } finally { controller = null; store.set((s) => ({ chat: { ...s.chat, streaming: false } })); }
}
function stop() { controller?.abort(); }                 // [■ 停止] 与 Esc 绑定
```

中断与错误语义约定：**用户主动停止** = AbortError → `interrupt()`（内容保留 + 「已中断」脚注，US5.3）；**网络层错误**（fetch reject / 流中断且非用户触发）= 自动降级 `POST /api/chat` 非流式重试一次，仍失败才报错（US5.3）；**应用层 error 事件** = 不降级，直接呈现统一错误体（模型输出不可信原则，§5 人机边界表）。

---

## 5. API 对接表

### 5.1 每视图 REST 端点（引自架构 §5.2）

| 视图 | 端点 | 方法 | 请求要点 | 响应要点 | 失败处理 |
|------|------|------|---------|---------|---------|
| 全局 | `/api/health` | GET | — | `{status, version, uptime_s}` | fetch 失败 → E5 全屏「服务未连接」 |
| 向导 | `/api/setup/status` | GET | — | `{run_id, steps[], current}`；无运行时 404 | 404 → 首跑引导（空态） |
| 向导 | `/api/setup/run` | POST | `{steps?, skip?}`（skip=已完成阶段，断点续跑） | 202 `{run_id, status}` | 400 STEP_INVALID → 文案；409 SETUP_RUNNING → 「部署进行中」 |
| 聊天 | `/api/chat/stream` | POST | `{model?, messages, options?}`；signal=AbortController | SSE：delta/usage/done/error | 预检失败 4xx/5xx → §5.2 映射；流中 error 事件 → 气泡错误态 |
| 聊天 | `/api/chat` | POST | 同上（降级路径，非流式） | `{message, usage, done}` | 同左 |
| 聊天 | `/api/models` | GET | — | `ModelInfo[]`（picker 数据源） | 503 → picker 禁用 + 错误条 |
| 模型 | `/api/models` | GET | — | 已装列表 | 503 OLLAMA_UNAVAILABLE → errorState + 去状态页 |
| 模型 | `/api/models/available` | GET | `device_profile`（来自 `/api/hardware`） | `CatalogEntry[]`（推荐目录） | 400 → 文案；空 → 「暂无推荐」 |
| 模型 | `/api/models/pull` | POST | `{name}` | 202 `{task_id}` | 400 MODEL_INVALID_NAME；409 PULL_IN_PROGRESS → 「已有任务」 |
| 模型 | `/api/models/{name}` | DELETE | name 需 `encodeURIComponent`（含冒号） | `{deleted:true}` | 404 MODEL_NOT_FOUND → toast + 刷新 |
| 状态 | `/api/system` | GET | — | `SystemInfo` | 503 OLLAMA_UNAVAILABLE → 卡片错误 + 重启入口（§6-X8） |
| 状态 | `/api/hardware` | GET | — | `HardwareReport{devices[], profile, source}` | 500 → errorState |
| 状态 | `/api/health/deep` | GET | 15s 轮询 + WS 事件触发 | `HealthReport`（恒 200，healthy 表达结论） | checks 内 fail 项 → 红叉 + remedy |
| 状态 | `/api/backends` | GET | — | `{active, chain[], health{}}` | 500 → errorState |
| 状态 | `/api/backends/select` | POST | `{name, force?}` | `{active:name}` | 400 BACKEND_UNKNOWN；503 → 文案 + [强制切换] |
| 状态 | `/api/ollama/restart` | POST | confirmModal 后调用 | `{restarted:true}` | 503 → toast + 排查指引 |
| 状态 | `/api/config` | GET | — | ConfigView（脱敏展示，只读） | 500 → 折叠为「配置不可用」 |
| 全局 | `/ws/events` | WS | 单连接全局 | §5.3 事件流 | 断线退避重连 + 45s 探活（§4.3） |

### 5.2 错误码 → 用户可读文案映射表（架构 §5.1 → zh-CN，D14）

`api.js` 的 `toUserError(err)` 统一产出 `UserError {code, title, detail, action?, traceId}`；`action` 为可点击的修复入口（如「去模型页」）。占位符 `{}` 由 `details` 字段填充。

| code | HTTP | title（用户可读） | detail / 动作 |
|------|------|------------------|--------------|
| `VALIDATION` | 400 | 请求内容没有通过校验 | 请检查输入后重试 |
| `CONFIG_INVALID` | 400 | 配置修改未通过校验 | 原配置已保留，未做更改 |
| `STEP_INVALID` | 400 | 部署阶段参数不正确 | 请从向导页面重新发起部署 |
| `MODEL_INVALID_NAME` | 400 | 模型名称格式不正确 | 正确形式如 `qwen2.5:3b` |
| `BACKEND_UNKNOWN` | 400 | 选择了未知的推理后端 | 请刷新页面后重试 |
| `MODEL_NOT_FOUND` | 404 | 本地没有安装模型「{details.model}」 | 已安装：{details.installed}；动作：去模型页 |
| `SETUP_NOT_FOUND` | 404 | 还没有运行过一键部署 | 动作：去向导页开始部署 |
| `ROUTE_NOT_FOUND` | 404 | 接口不存在 | 前端与服务版本可能不匹配，请刷新 |
| `PULL_IN_PROGRESS` | 409 | 已有一个拉取任务在进行中 | 请等待当前任务完成 |
| `SETUP_RUNNING` | 409 | 部署正在进行中 | 请等待当前部署结束 |
| `RATE_LIMITED` | 429 | 请求太频繁了 | 请稍候再试 |
| `INTERNAL_ERROR` | 500 | 服务内部出错 | trace_id：{trace_id}（反馈时请附上） |
| `OLLAMA_UNAVAILABLE` | 503 | 连不上 Ollama（127.0.0.1:11434） | 动作：去状态页重启 Ollama |
| `BACKEND_UNHEALTHY` | 503 | 推理后端当前不可用 | 动作：去状态页体检 |
| `MODEL_NOT_LOADED` | 503 | 模型「{details.model}」尚未就绪 | 动作：去模型页拉取 |
| `UPSTREAM_TIMEOUT` | 504 | 模型响应超时 | CPU 模式生成较慢，请重试或换更小模型 |
| （网络层 TypeError） | — | 连不上 AIE 服务（127.0.0.1:8189） | 请确认 `aife serve` 正在运行；动作：重试 |
| （WS error 事件） | — | {message} | 附带 code 与 trace_id，全局 toast |

### 5.3 SSE 事件处理表（`/api/chat/stream`）

| 事件 | data 要点（schema 待定型，§6-X1） | 前端处理 |
|------|----------------------------------|---------|
| `delta` | `{text}` | `renderer.appendDelta(text)`（rAF 批量刷新） |
| `usage` | `{prompt_tokens, completion_tokens, ...}` | `renderer.setUsage` → 完成脚注展示 |
| `done` | `{done_reason?}` | `renderer.finalize()`（正常收尾） |
| `error` | 统一 error 体（§5.1） | `renderer.fail(toUserError(data))`（不降级） |

---

## 6. 与后端契约的对齐检查（【待确认】清单，交回主理人）

逐条核对架构 §5.2/§5.3 后，前端需要但契约缺失/含糊的点如下（X# 编号供回执引用）：

| # | 契约缺口 | 影响的前端功能 | 前端缓解（不等契约也能做） | 建议方案 | 优先级 |
|---|---------|---------------|---------------------------|---------|--------|
| X1 | SSE 事件只列了事件名（delta/usage/done/error），**data 负载 schema 未定型** | streamRenderer 无法定型，字段名猜错即白屏 | 按 §5.3 草案容错解析（`?.` + 默认值） | data 统一 JSON：`delta:{text}`、`usage:{prompt_tokens,completion_tokens}`、`done:{done_reason?}`、`error:{§5.1 error 体}` | **P0** |
| X2 | `/api/setup/run` 的 `steps?/skip?` **step 枚举未列全**（CLI 是 `--skip-deps/--skip-ollama/--skip-model`，bootstrap 阶段还有 hardware/verify/start） | 向导「重试本阶段」按钮与时间线渲染 | 前端不硬编码枚举，按 status 返回的 steps[] 动态渲染 | 在 03-api-contract 固化 step 字典：`deps/hardware/ollama/model/verify/start` | **P0** |
| X3 | `setup.error.remedy` **类型未定**（string 还是结构） | US6.3「可直接复制执行的命令」——一键复制按钮需要 commands 数组 | 容错：string → 单条；array → 多条；对象 → 取 commands | `remedy: {summary: string, commands: string[], doc?: string}` | **P0** |
| X4 | `GET /api/setup/status` 无运行时返回 404，**无法表达「历史成功过」** | 首屏路由决策（§1.1）只能靠 404/200 二分 | 404 → 首跑引导（可接受） | 增加 `status:'idle'` + `last_run:{run_id,status,finished_at}`；404 语义保留给「run_id 不存在」 | P1 |
| X5 | **WS 断线后是否补发进度未规定** | setup 进行中掉线 → 进度丢失 | 前端缓解：重连成功后主动 `GET /api/setup/status` 补偿 + 日志面板标注「已重新同步」 | 服务端无需重放；把「重连后补偿查询」写入 03-api-contract 的客户端约定 | P1 |
| X6 | `HealthReport.checks` **子项 schema 未定型**（只有键名 aife/ollama/models/backend/disk） | 状态页健康列表无法定型；disk 要展示余量数值 | 容错渲染：`{ok, summary}` 必有，`detail/remedy` 可选 | `check: {ok: boolean, summary: string, detail?, remedy?}`；disk.detail 含 `{free_gb, total_gb}` | **P0** |
| X7 | `HardwareReport.devices[]` **字段与证据等级表达未定型**（ADR-007 只说「带 source 证据等级」） | deviceCard / evidenceTag 依赖字段名 | 容错：缺字段显示「—」 | `device: {type, name, vram_gb?, source: 'E0'|'E1'|'E2'|'E3', caveats?: string[]}`；profile 取值与 §4 `hardware.device` 枚举一致（auto 解析后的实际剖面） | **P0** |
| X8 | `/api/system` 在 Ollama 不可用时返回 **503 OLLAMA_UNAVAILABLE** | 状态页首屏无法区分「aife 没起」（fetch 失败）与「Ollama 没起」（503），错误文案分叉 | 前端按「fetch 失败 vs 503」分叉文案（可接受） | 建议恒 200：`ollama_version=null` + 增 `ollama_reachable: boolean` | P1 |
| X9 | `/api/chat` 的 `options?` **透传白名单未定** | 聊天参数面板能调什么 | 前端只做白名单控件，多传不报错即忽略 | 白名单：`temperature/top_p/num_ctx/seed`；范围与默认值以后端为准 | P1 |
| X10 | **后端 fallback 发生在前端还是后端未明确**（US5.4） | 若前端自实现 fallback 链，复杂度失控 | 前端只调 `/api/chat/stream`，由 `BackendRegistry` 内部 fallback，前端监听 `backend.changed` 提示 | 明确：fallback 在后端内部完成，前端无感 | P1 |
| X11 | `model.pull_progress` 的 **status 枚举与单位未定** | 拉取进度条阶段文案（下载中/校验中） | 前端按 completed/total 算百分比，status 仅作文案补充 | `status ∈ [downloading, verifying, success, error]`；completed/total 为字节 | P1 |
| X12 | `/api/models/available` 的 `device_profile` 取值需与硬件枚举对齐 | 推荐目录查询参数 | 前端直接透传 `/api/hardware` 的 profile 值 | 确认枚举集合一致（cuda/rocm/xpu/mps/directml/npu/cpu） | P2 |
| X13 | `DELETE /api/models/{name}` 对含冒号模型名（`qwen2.5:3b`）的 URL 匹配 | 删除功能 404 误判 | 前端 `encodeURIComponent(name)` | 后端确认 path converter 接受编码冒号（Starlette 默认支持，确认即可） | P2 |
| X14 | `/api/config` PATCH **可改字段白名单未列** | 「设为默认模型」等设置按钮能否做 | v1 前端**只读展示** config，不做 PATCH UI | v1 确认只读；若做设置 UI 需白名单 + CONFIG_INVALID 文案 | P2 |
| X15 | `log.line` 「受 log_level 控制」——**setup 期间是否至少 info 级广播未定** | 向导日志面板完整性 | 无 log.line 时仅渲染 step_progress.message（时间线仍完整） | setup 运行期间 log.line 保底 info 广播 | P2 |
| X16 | `health.changed` **触发时机未定**（配置热切换/Ollama 重启时是否广播） | 状态页实时性 | 前端 15s 轮询 `/api/health/deep` 兜底 + 事件即时刷新 | 明确广播时机（至少：backend.changed、ollama restart、deep 结论翻转时） | P2 |
| X17 | 架构 §2 目录树未包含 `web/store.js`、`web/ws.js`、`web/ui/`、`web/mock/` | 无契约影响，属文档同步 | 已在 §3.1 声明为前端内部细化 | 主理人确认是否回写 02-architecture §2 目录树；`web/mock/` 需在 `scripts/build-release.sh` 打包时排除 | P2 |

**联调计划（M3，与程不宕协同）**：① `/api/health` + `/api/system`（状态页骨架）→ ② `/api/hardware`（证据标签）→ ③ `/api/models` + `/available` → ④ `/api/chat` 非流式 → ⑤ `/api/chat/stream` SSE（X1 定型后）→ ⑥ WS 全事件 + setup 向导端到端（X2/X3 定型后）→ ⑦ 异常注入（404/409/503/504、断网、杀 WS 连接、杀 Ollama）。
**Mock 方案**：`web/mock/mockHandlers.js` 经 `localStorage.aife_mock=1` 开启，在 `api.js` 的 fetch 入口拦截（零依赖）；该目录**不进分发包**（build-release.sh 排除，X17）；联调环境一律真实后端，mock 仅用于无后端时的 UI 自测。

---

## 7. 设计令牌与规范（浅色主题，D14）

### 7.1 色彩（含对比度实测，浅色主题）

| 令牌 | 值 | 用途 | 对比度（on #fff，实测） |
|------|----|------|----------------------|
| `--bg` | `#f6f7f9` | 页面底 | — |
| `--panel` | `#ffffff` | 卡片/面板 | — |
| `--border` | `#e2e6ec` | 边框（仅装饰，不承载信息） | — |
| `--text` | `#1a202c` | 正文 | ≈16:1（AAA） |
| `--muted` | `#5b6675` | 次要文字 | ≈5.8:1（AA） |
| `--accent` | `#2b6cb0` | 主色/链接/焦点 | ≈5.4:1（AA） |
| `--accent-soft` | `#e8f0fe` | 选中/悬停底 | — |
| `--ok` | `#1e7a45` | 成功 | ≈5.3:1（AA） |
| `--warn` | `#8a5a10` | 警告文字 | ≈5.9:1（AA） |
| `--warn-soft` | `#fff8e6` | 警告底 | — |
| `--danger` | `#c0392b` | 错误/危险操作 | ≈5.4:1（AA） |
| `--danger-soft` | `#fdecea` | 错误底 | — |

> 继承 Octop 浅色令牌，**三处 AA 修正**：`--muted` `#6b7684→#5b6675`、`--ok` `#2e8b57→#1e7a45`、`--warn` `#b7791f→#8a5a10`（原值作 12px 文字时对比度不足 4.5:1）。所有正文/图标信息不单独依赖颜色传达（配文字/形状）。

### 7.2 字号 / 间距 / 圆角 / 断点

| 维度 | 令牌 |
|------|------|
| 字号 | 12（辅助/脚注）/ 13（紧凑表格）/ 14（正文，基准）/ 16（强调）/ 20（视图标题）；行高 1.5；字体栈 `system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`（无 webfont，离线可用） |
| 间距 | 4 / 8 / 12 / 16 / 24（4 的倍数） |
| 圆角 | 6（控件）/ 8（卡片）/ 20（pill 徽章） |
| 阴影 | `0 1px 3px rgba(16,24,40,.08)` |
| 断点 | **≥1024px**：wizard/status/models 两栏，chat 居中 860px；**640–1023px**：全部单栏堆叠（wizard 日志折叠为 `<details>`）；**<640px**：紧凑模式——控件高度 ≥44px、tab 横向可滚动、按钮全宽、消息流贴边 |

> 移动场景说明：MVP 服务默认仅 127.0.0.1（D10），「手机访问」指本机窗口缩放/窄屏模拟；前端保证 375px 宽不破版、核心流程（发消息/拉模型/看状态）可用，但不做移动端专属交互（PWA/触摸手势等列入演进）。

### 7.3 无障碍基线

- **键盘**：全部交互用原生 `<button>/<select>/<input>`；tab 导航支持 ←→ 方向键（WAI-ARIA tabs 模式）；Esc 关闭 modal；聊天 Enter 发送 / Shift+Enter 换行 / Esc 停止生成；`focus-visible` 2px `--accent` 外描边 + 2px offset
- **语义与 ARIA**：`<html lang="zh-CN">`；视图容器 `role="tabpanel"` + `aria-labelledby`；消息流 `role="log" aria-live="polite"`，流式气泡 `aria-busy="true"`；toast `role="status"`，错误 `role="alert"`；证据标签/健康徽章文字自带（不只有颜色）
- **对比度**：全部文本 ≥4.5:1（§7.1 实测）；焦点环可见；`prefers-reduced-motion` 时关闭流式光标闪烁与进度条动画
- **动效**：过渡 ≤250ms；无自动播放动画；无视差
- **国际化基线**：v1 仅 zh-CN（D14）——页面模块顶部集中文案对象 `const S = {...}`，不引 i18n 库；日期/体积/数量用 `Intl` 按 `zh-CN` 格式化；演进多语言/暗色时把 S 抽为 `web/i18n/`、令牌加 `[data-theme]` 即可，不动组件结构

### 7.4 响应式与降级

- 布局全部 CSS Grid/Flex（无浮动）；`min-width:0` 防栅格溢出；长文本/模型名 `word-break: break-all`
- 窄屏下 wizard 日志区折叠、models/status 双栏堆叠且顺序保持「主要信息在上」
- 窗口 <640px 时顶栏状态区收缩为仅 WS 灯 + 健康徽章（title 展示详情）

---

## 8. 性能、监控与验收

### 8.1 性能预算（对齐架构 §6 非功能性目标）

| 指标 | 目标 | 优化手段 |
|------|------|---------|
| LCP | ≤1.0s（127.0.0.1 回环） | 零外部请求/零 webfont；单 css <15KB；首屏不等待任何业务数据（骨架先行） |
| INP | ≤100ms | 流式文本 rAF 批量刷新 + `textContent` 追加（不重排整窗）；WS/SSE 消息处理 <8ms；无同步 IO |
| CLS | ≤0.01 | 流式气泡 min-height 预留 + 滚动锚定；tab 切换不抖动 |
| 初始 JS | ≤60KB 未压缩 | 无框架；四视图 `import()` 按需分包；公共 chunk 仅 store/api/ws/dom |
| WS 稳定性 | 断线 ≤3s 重连 | 退避重连（1s→8s 封顶）+ 45s 无帧判掉线 + setup/status 补偿（X5） |
| 内存 | 长会话无泄漏 | 视图 unmount 退订/清定时器；日志面板截断保留最近 500 行；消息流虚拟化列入演进 |

### 8.2 「监控」与埋点（D16 裁决：不实现遥测，代码中不留埋点）

v1 **无任何遥测埋点、无数据外发**。本地可观测性仅三点：① 全局错误边界（`error`/`unhandledrejection`）→ toast 展示 + `console.error`；② 顶栏 WS 连接灯 + 健康徽章；③ 错误态展示后端 `trace_id`（供用户反馈时引用，与日志 trace_id 一致）。

### 8.3 浏览器手工验收 checklist（凌无缺可直接执行）

| # | 验收项 | 操作 / 命令 | 通过标准 | 对应 |
|---|-------|------------|---------|------|
| 1 | 静态托管可用 | `aife serve` 后访问 `http://127.0.0.1:8189` | 四 tab 页面加载，无控制台报错 | US5.2 |
| 2 | **无 node_modules** | 仓库根执行 `grep -rn "node_modules" web/` 与 `find . -name node_modules -not -path "./.git/*"` | 均无输出；`ls web/` 只有 .html/.js/.css 与子目录 | US5.2 |
| 3 | 无外部依赖（离线可用） | `grep -rnE "https?://" web/index.html web/app.js web/api.js web/store.js web/ws.js web/pages/*.js web/ui/*.js`（排除注释） | 无外部域请求；断网后刷新页面骨架仍渲染 | US5.2 / 离线 |
| 4 | Network 面板 | 全程操作 + devtools Network | 无跨域外部请求；失败请求仅 127.0.0.1 | US5.2 |
| 5 | 发消息收回复 | 聊天页输入「你好，请用一句话介绍你自己」回车 | 逐字流式出现；完成后显示用量脚注 | US5.1 / A5 |
| 6 | 停止生成 | 生成中点 [■ 停止]（或 Esc） | 立即停止；已生成内容保留并标「已中断」 | US5.3 |
| 7 | 后端故障可解释 | 停掉 Ollama 后发消息 | 显示 BACKEND_UNHEALTHY/OLLAMA_UNAVAILABLE 可读文案 + 修复入口（或后端内部 fallback + `backend.changed` 提示） | US5.4 |
| 8 | 模型拉取 | 模型页拉取 `qwen2.5:1.5b` | 任务条进度推进；完成后进入已装列表 + toast | US4.1 |
| 9 | 重复拉取 | 拉取进行中再次拉取同模型 | 409 PULL_IN_PROGRESS → 「已有拉取任务在进行中」 | §5.1 |
| 10 | 删除确认 | 删除一个模型 | confirmModal 二次确认；确认后列表移除 | US4.2 |
| 11 | 向导成功路径 | 新环境（或重装后）点 [开始一键部署] | 步骤时间线逐项打勾；完成后自动跳 `#/chat` | US1.1 |
| 12 | **向导失败可解释** | 注入失败（先占用 11434 端口 / 断网后部署） | 失败步骤标红；卡片展示「卡在第几步 / 为什么（code+message）/ 怎么修（命令可一键复制）/ 重试本阶段」 | US1.2 / US6.3 |
| 13 | 五态全覆盖 | 逐视图触发空/加载/错误（删空模型、断网、杀 WS） | 无白屏、无裸 JSON、无 `alert()` 弹窗 | §1.3 |
| 14 | 窄屏可用 | 浏览器窗口缩至 375px 宽 | 布局堆叠不破版；发消息/拉模型/看状态可完成 | §7.2 |
| 15 | 键盘全流程 | 仅用 Tab/Enter/←→/Esc | 可切换视图、可发消息、可停止、可开关 modal | §7.3 |
| 16 | WS 重连 | 运行中重启 `aife serve` | ≤3s 重连；顶栏灯态变化；setup 进行中有「已重新同步」补偿 | §4.2 / X5 |
| 17 | 刷新保持 | 任意视图按 F5 | hash 路由保持当前视图 | §1.1 |
| 18 | XSS 防护 | 让模型输出一段 `<img src=x onerror=alert(1)>` | 按纯文本展示，不执行；错误 message/日志同理 | §3.1 红线 |

---

## 9. 结论与交接

- 本方案零框架、零构建、零外部依赖，直接落地架构 §2 的 `web/` 蓝本；四视图 + 全局 WS/SSE 双通道 + 五态全覆盖。
- **交回主理人**：§6 的 X1–X3、X6–X7 为 P0 级契约缺口（阻塞 streamRenderer 与状态页定型），请协调程不宕在 03-api-contract 中固化；X4–X11 为 P1；X12–X17 为 P2。
- **交程不宕**：SSE data schema（X1）、setup step 字典（X2）、remedy 结构（X3）、HealthReport 子项 schema（X6）、HardwareReport devices 字段与证据等级表达（X7）五项，前端将按 §6「建议方案」容错实现，契约定型后移除容错分支。
- **交凌无缺**：§8.3 checklist 可直接转为手工验收用例；第 2、3、12、18 项为硬性验收。

—— 颜可心（前端体验工程师），Phase 2 前端侧交付完毕。
