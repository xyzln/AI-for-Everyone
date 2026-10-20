# AIE（AI For Everyone）服务设计与 API 契约 v1.0

> **文档定位**：Phase 2 服务侧唯一权威契约。实现组按本文写代码；凌无缺按本文写测试；颜可心按 §4（WS）与 §5（SSE）写前端；安智体的剖面/配置键、储海量的数据模型与本文接口字段对齐。
> **作者**：程不宕（后端服务工程师）
> **输入**：`docs/design/01-requirements.md` v0.1（US/A/S/D 编号）、`docs/design/02-architecture.md` v1.0（§5 接口契约框架全量、§4 配置项、§11 裁决 D7–D16）、Octop 源码已证契约缺陷（错误码不统一 / 部分路由无错误处理 / BackendHealth 非 pydantic / EventBus 静默丢帧）。
> **状态**：v1.1 待评审。v1.1 = 与 `docs/design/04-data-model.md` v1.0 全量对齐（ConfigView 分段脱敏 + masked_fields、CONFIG_READONLY 错误码、SetupRun 七阶段台账、RegistrySnapshot、PullTask 防重规则、热切换五值口径），变更明细见 §13-15~19。所有响应模型均为 pydantic v2 `BaseModel`，OpenAPI 可完整导出（修正 octop 缺陷）。本文是架构 §5 的**细化落地**，不推翻架构；所有不一致/补充显式列于 §13。
> **关键裁决引用**：D10（默认仅 127.0.0.1）、D13（配置在 `~/.aife/config.yaml`）、D6（外部 API 回退不降级、接口预留）、D11（Ollama ≥ v0.5.0，`/api/ps` 缺失降级不报错）。

---

## 0. 术语与阅读约定

| 术语 | 含义 |
|---|---|
| managed Ollama | 本次 `aife serve` 由 OllamaManager 拉起的子进程（持句柄，可管其生命周期） |
| adopted Ollama | `aife serve` 启动前已在 `ollama.host:port` 运行的外来进程（采纳可用，但**永不杀死**） |
| DOMAIN_REASON | 大写蛇形稳定错误码（如 `MODEL_NOT_FOUND`），客户端只依赖 code，不依赖 message 文案 |
| 证据等级 E0–E3 | E0 实测 / E1 工具输出 / E2 推断 / E3 猜测（硬件探测契约，`server/schemas.py` 中为 `EvidenceLevel`） |
| trace_id | 请求级关联 ID，响应头 `X-Trace-Id`、错误体、日志三处一致 |

通用约定：

1. **时间**：一律 RFC 3339 UTC（pydantic `datetime` 序列化为 `2025-01-01T00:00:00Z` 形态）。
2. **单位**：字节数 `size` 为 int 字节；时长带后缀（`_s` 秒 float / `_ms` 毫秒 float）；磁盘 `*_gb` 为 float GB（1GB=1024³B）。
3. **枚举**：JSON 中一律小写字符串（`"cuda"`/`"ollama"`），代码中 `str, Enum`。
4. **成功响应无信封**：直接返回资源对象；**失败响应恒为** `{"error": {code, message, details, trace_id}}`（§3）。成功响应绝不携带 `error` 字段。
5. **所有响应带 `X-Trace-Id` 头**（§6.4）。
6. **并发**：本地单用户；除 §8 明确的状态守卫外，路由不设应用层串行锁。

---

## 1. 服务与模块结构

### 1.1 服务进程模型

```
┌─ aife CLI（aife serve，argparse）──────────────────────────────┐
│                                                                │
│  aife-server 进程（uvicorn + FastAPI，单事件循环）              │
│  ├─ 接入层：routes/*（REST）、ws.py（WS）、sse.py（SSE 编码）    │
│  ├─ 应用层：routes/setup.py 编排 bootstrap.py                   │
│  ├─ 领域层：backends/*（Registry+fallback）、models/*、hardware │
│  ├─ 基础设施：runtime.py（唯一组装点）、ollama/manager.py       │
│  │           └─ OllamaManager 看门狗 task（§1.4）               │
│  └─ EventBus（WS 广播，每连接有界队列，§4.6）                    │
│                                                                │
│  Ollama 子进程（:11434，manager 注入 OLLAMA_* 环境变量）        │
└────────────────────────────────────────────────────────────────┘
        浏览器 127.0.0.1:8189 ──REST/WS/SSE──▶ aife-server ──HTTP NDJSON──▶ Ollama
```

**MVP 单进程部署**：server 与看门狗同进程同事件循环，不拆微服务（本地单用户工具，拆分只增加运维面与故障域）。依赖方向遵循架构 §1.3 R1–R4：领域层禁 import fastapi；runtime 是唯一组装点；反向通知只走 EventBus。

### 1.2 服务清单

| 服务/进程 | 职责 | 依赖 | 技术栈 |
|---|---|---|---|
| aife-server（uvicorn+FastAPI） | REST/WS/SSE 契约、静态托管 `web/`、统一错误体 | runtime、BackendRegistry、OllamaManager | fastapi + uvicorn |
| OllamaManager 看门狗（server 内 asyncio task） | Ollama 拉起/守护/退避重拉/优雅退出 | ollama 二进制、hardware 剖面 env | subprocess + httpx |
| Ollama 子进程（:11434） | 推理与模型管理（`/api/chat` `/api/tags` `/api/pull`…） | 模型文件（OLLAMA_MODELS） | Ollama ≥ v0.5.0（D11） |
| aife CLI serve 入口 | 启动序列、信号处理、退出码 | 上述全部 | argparse |

### 1.3 `aife serve` 启动序列（8 步，每步含失败行为）

| # | 步骤 | 失败行为（退出码） |
|---|---|---|
| 1 | argparse 解析 `--host --port --config --no-browser --log-level`；校验 `server.port ≠ ollama.port` | 端口相同 → 打印原因，退出码 **1** |
| 2 | 加载配置 `~/.aife/config.yaml`（D13；不存在则从模板 `config/aife.yaml` 复制生成）；`${VAR}` 展开 + pydantic 校验 | 校验失败 → 指明字段，退出码 **2** |
| 3 | 绑定预检：尝试 bind `host:port`；若 `host ≠ 127.0.0.1` → 终端 + 日志 **WARNING** 明示裸露风险（D10，README 同步） | 端口占用 → 提示 `aife serve --port 8190` 式修复命令（US6.3），退出码 **4** |
| 4 | runtime 组装（唯一组装点）：config → hardware probe（**缓存 + 失败降级 CPU 剖面 + E2/E3 标注**，ADR-002）→ OllamaManager → BackendRegistry → EventBus | 探测失败不阻断（降级），仅 WARNING |
| 5 | `OllamaManager.ensure_running()`：① GET `/api/version`（2s 超时）探测已有 Ollama → 有则 **adopted**，跳过启动；② 无且 `ollama.autostart=true` → 按剖面 env 拉起子进程，轮询 `/api/version` 就绪（**就绪超时 30s，间隔 0.5s**）；③ 无且 autostart=false → 继续（deep health 标记 ollama 失败，`/api/chat` 返回 503） | ②超时 → 输出子进程 stderr 尾 20 行 + doctor 指引，退出码 **3** |
| 6 | uvicorn 启动（`timeout_graceful_shutdown=10s`）；启动完成写日志 `event=serve.ready`（含 url、trace 前缀） | uvicorn bind 失败 → 退出码 4 |
| 7 | 健康自检：进程内命中 `/api/health`（liveness 必须 ok，否则 **5**）；`/api/health/deep` **异步**跑一次，结果经 WS 广播 `health.changed`，**不阻塞启动** | liveness 失败 → 退出码 5 |
| 8 | `server.open_browser=true` 且未传 `--no-browser` → 延迟 0.5s `webbrowser.open("http://127.0.0.1:{port}/")`；失败仅 WARN | 不阻断 |

> 启动到可接受请求 < 3s（架构 §6）：torch 惰性导入、不预热模型、路由模块化。

### 1.4 优雅退出序列与 Ollama 子进程处置规则

收到 SIGINT/SIGTERM：

1. uvicorn 停止接受新连接；向全部 WS 连接广播扩展事件 `server.shutdown`（payload `{reason:"sigterm"}`）后以关闭码 **1001** 关闭；SSE 流直接关闭（进行中的 chat 允许最多 10s 收尾，超时取消）。
2. **Ollama 处置规则（硬规则，含新增配置项）**：

| Ollama 来源 | `ollama.shutdown_on_exit=true`（默认） | `ollama.shutdown_on_exit=false` |
|---|---|---|
| **managed**（本进程拉起） | **停止**：POSIX `SIGTERM` / Windows `taskkill /T` 树杀 → 等待 10s → `SIGKILL`/`TerminateProcess` | 保留运行，日志 INFO 告知 pid+端口 |
| **adopted**（启动前已存在） | **保留**——规则：*不杀不是自己拉起的进程* | 保留 |

3. `BackendRegistry.close_all()`（httpx client 关闭）→ flush 日志 → 退出码 0。

> 配置项 `ollama.shutdown_on_exit`（bool，默认 true）为本文新增键（架构 §4 未含，理由：进程模型必须可回答"aife 退出后 Ollama 是否留存"，详见 §13-10）。`false` 的典型场景：用户希望 Ollama 常驻供其他客户端使用。

### 1.5 崩溃守护规则（Ollama 看门狗）

```
running ──子进程非预期退出/僵死──▶ restarting ──重拉成功──▶ running
   ▲                                    │
   └──────────── health.changed ◀── unhealthy（3 次全败 → 放弃，doctor 报错）
```

| 规则 | 定义 |
|---|---|
| 检测 | 双保险：① 子进程 `wait()` 协程；② 每 2s `GET /api/version` 探测（防僵死） |
| 退避重拉 | 第 n 次重拉间隔 = `5s × n`（5s / 10s / 15s），**最多 3 次**（对齐架构 §6「5s 内退避重拉，最多 3 次」） |
| 放弃 | 3 次全败 → 状态 `unhealthy`：ERROR 日志（含 stderr 尾 20 行 + `aife doctor` 指引）、WS 广播 `health.changed{healthy:false}`；`aife doctor` 检查项 `ollama_process` 可检出（US6.1） |
| 恢复 | 后续重拉成功 → 广播 `health.changed{healthy:true}` |
| 防误判 | `restarting` 状态（手动 restart / 配置热切换重启 / 启动就绪等待）期间看门狗暂停，不双启 |
| adopted 崩溃 | **不管**（非本进程责任）：WARNING 日志 + deep health 标记 ollama 失败，不重拉 |

### 1.6 配置热切换与 Ollama 重启联动（ADR-003 落地）

配置热切换的逐键口径（`热生效`/`需重启 Ollama`/`需重启 aife-server`/`下次运行生效`/`只读`）以 04-data-model.md §2.1「热切换」列为权威，API 行为映射见 §2.5.2。`PATCH /api/config` 命中派生 env 键（`ollama.host/port/keep_alive/num_gpu/max_loaded_models/models_dir`）时：reload 后比对新旧 env → 有差异且 Ollama 为 **managed** → 自动重启子进程（看门狗 `restarting` 态，广播 `health.changed`）；为 **adopted** → WARNING「改动将在 Ollama 下次重启后生效」，不擅动外来进程。

### 1.7 分层结构与目录组织（server 侧细化，对齐架构 §2）

```
aife/server/
├── app.py      # create_app()：中间件顺序 TraceId→CORS→AccessLog；异常处理器注册；静态挂载；include_router
├── errors.py   # ErrorCode(str,Enum) + AIEError 体系 + HTTPException→统一体 映射 + 全局 handler
├── schemas.py  # 全部 pydantic 请求/响应模型（含 HealthReport/BackendHealth，均为 BaseModel）
├── deps.py     # 依赖注入：get_runtime/get_registry/get_manager（测试可 override）
├── ws.py       # EventBus（有界队列+seq+背压可观测）+ /ws/events endpoint + 30s 心跳 task
├── sse.py      # 【新增】SSE 事件编码、15s 注释心跳、X-Accel-Buffering 头（架构 §2 未列，§13-11）
└── routes/     # health / system / models / chat / backends / setup / ollama 七个模块
```

依赖规则：routes → runtime/bootstrap/models；routes **禁止**互相 import；backends 不知道 server 存在；ws.py 只经 runtime 取 EventBus（R4：反向通知走总线不走 import）。

---

## 2. 接口实现设计

### 2.0 路由总表（速查；每路由详约在 §2.x）

| API | 方法 | 同步/异步 | 错误码（路由特有触发；通用定义见 §3） | 详约 |
|---|---|---|---|---|
| /api/health | GET | 同步 | 500 兜底 | §2.1 |
| /api/health/deep | GET | 同步（内部并发探测） | 500 兜底；**恒 200**，healthy 表达结论 | §2.2 |
| /api/system | GET | 同步 | 503 OLLAMA_UNAVAILABLE | §2.3 |
| /api/hardware | GET | 同步（缓存探测） | 500 兜底（探测失败降级 CPU 不报错） | §2.4 |
| /api/config | GET | 同步 | 500 兜底 | §2.5 |
| /api/config | PATCH | 同步（热切换） | 400 CONFIG_INVALID、409 CONFIG_RESTART_REQUIRED、500 CONFIG_RELOAD_FAILED | §2.5 |
| /api/models | GET | 同步 | 503 OLLAMA_UNAVAILABLE | §2.6 |
| /api/models/available | GET | 同步 | 400 VALIDATION | §2.7 |
| /api/models/pull | POST | 异步（**202**，WS 进度） | 400 MODEL_INVALID_NAME、409 PULL_IN_PROGRESS、503 | §2.8 |
| /api/models/{name} | DELETE | 同步 | 404 MODEL_NOT_FOUND、503 | §2.9 |
| /api/chat | POST | 同步 | 400、404 MODEL_NOT_FOUND、503 BACKEND_UNHEALTHY / MODEL_NOT_LOADED、504 UPSTREAM_TIMEOUT | §2.10 |
| /api/chat/stream | POST | 异步（SSE） | 预检失败返 4xx/5xx JSON；流中错误以 error 事件（§5） | §2.11 |
| /api/backends | GET | 同步（并发健康探测） | 500 兜底 | §2.12 |
| /api/backends/select | POST | 同步 | 400 BACKEND_UNKNOWN、503 BACKEND_UNHEALTHY（force 豁免） | §2.13 |
| /api/setup/run | POST | 异步（**202**，WS 进度） | 400 STEP_INVALID、409 SETUP_RUNNING | §2.14 |
| /api/setup/status | GET | 同步 | 404 SETUP_NOT_FOUND | §2.15 |
| /api/ollama/restart | POST | 同步（≤30s） | 409 OLLAMA_NOT_MANAGED、503 OLLAMA_UNAVAILABLE | §2.16 |
| /v1/models | GET | 同步 | 503 OLLAMA_UNAVAILABLE | §2.17 |
| /v1/chat/completions | POST | 同步/SSE | OpenAI 形状错误信封（§2.17.4） | §2.17 |
| /ws/events | WS | 长连接 | error 事件 | §4 |

### 2.1 GET /api/health（liveness 探活，对齐 US6.4）

- **响应 200** `HealthLiveness`：

| 字段 | 类型 | 说明 |
|---|---|---|
| status | `Literal["ok"]` | 恒 "ok"——进程活着即 200 |
| version | str | aife 版本（`aife.__version__`） |
| uptime_s | float | 进程启动至今秒数 |

- **错误码**：500 INTERNAL_ERROR（兜底；本路由无外部依赖，实际不可达）。
- **语义**：仅供探活（`curl 127.0.0.1:8189/api/health`）；不探测 Ollama——后端状态看 `/api/health/deep`。

### 2.2 GET /api/health/deep（深度体检，恒 200）

**响应 200** `HealthReport`（pydantic，修正 octop 非 pydantic 缺陷）：

| 字段 | 类型 | 说明 |
|---|---|---|
| healthy | bool | 全部 checks.ok 的合取 |
| checks | `HealthChecks` | 五个固定子项（见下） |
| checked_at | datetime | UTC |

`HealthChecks` 五个子项均为 `CheckResult{name:str, ok:bool, detail:str="", duration_ms:float=0}`：

| 子项 | 探测内容 | ok 条件 |
|---|---|---|
| aife | 版本 + uptime | 恒 true |
| ollama | `GET {ollama}/api/version`（2s 超时） | 200 且版本 ≥ v0.5.0（D11）；`/api/ps` 404 时降级为「不探测已加载模型」而非报错 |
| models | `GET {ollama}/api/tags` | 可达；detail 含已装数量 |
| backend | 当前后端 `health()` | 可达**且非缺模型**（「缺模型判不健康」，M14 教训；detail 缺模型时给出 `MODEL_NOT_LOADED` 语义说明） |
| disk | `~/.aife` 与 OLLAMA_MODELS 所在盘空闲 | 空闲 ≥ 5GB；<5GB ok=false；<10GB detail 附警告 |

- **并发**：五个子项 `asyncio.gather` 并发，单项超时 3s，总预算 5s。
- **错误码**：500 INTERNAL_ERROR（兜底）。
- **副作用**：后台 task 每 30s 跑一次，结论翻转时广播 `health.changed`（§4.5）。

### 2.3 GET /api/system

**响应 200** `SystemInfo`：

| 字段 | 类型 | 说明 |
|---|---|---|
| version | str | aife 版本 |
| platform | str | `platform.platform()`，如 `Windows-11-10.0.26100-SP0` |
| python | str | `platform.python_version()` |
| ollama_version | str | 来自 `/api/version` |
| profile | str | 剖面 key：`cuda/rocm/xpu/mps/directml/npu/amd_rocm/cpu` |
| active_backend | str | 当前后端名（`ollama`） |

- **错误码**：503 OLLAMA_UNAVAILABLE（取版本失败，details 含 `host/port/hint`）。
- **并发**：只读，可并发。

### 2.4 GET /api/hardware

**响应 200** `HardwareReport`：

| 字段 | 类型 | 说明 |
|---|---|---|
| devices | list[`DeviceInfo`] | 探测到的设备列表 |
| profile | `ProfileInfo` | 求解出的剖面 |
| source | `EvidenceLevel` | 整报告最高证据等级 |

`DeviceInfo{type: DeviceType, name: str, vram_gb: float\|null, evidence: EvidenceLevel, detail: str=""}`（`DeviceType ∈ cuda/rocm/xpu/mps/directml/npu/cpu`）。
`ProfileInfo{key: str, vendor: str, ollama_accel: str, env: dict[str,str], caveats: list[str]}`（`env` 为将注入 Ollama 子进程的 `OLLAMA_*` 项；`caveats` 保留 NPU 实验性标注，D3）。

- **错误码**：500 INTERNAL_ERROR（兜底）。**探测失败按 ADR-002 降级 CPU 剖面 + E2/E3 标注 + 显式警告，不返回错误**（S3：无证据等级输出视为不合格）。
- **并发**：探测结果进程内缓存（`hardware.py` 单次探测），可并发；强制重探测走 CLI `aife detect`（v1 无 API 重探测端点，§14 待确认）。

### 2.5 /api/config（GET 脱敏 / PATCH 热切换）

#### 2.5.1 GET /api/config

**响应 200** `ConfigView`（v1.1 对齐 04-data-model.md §6.2：**分段 pydantic 模型**，弃用 v1.0 的 `values` 通用 dict——分段模型 OpenAPI 可导出性更优，ADR-006）：

| 字段 | 类型 | 说明 |
|---|---|---|
| config_version | int | 恒 1 |
| hardware / ollama / models / backends / openai_compat / server / network / setup / bench / logging | 各段 `*ConfigView` | 与配置文件同构的分段视图；字段级 schema（类型/默认/校验）以 04-data-model.md §2.1 各表为权威 |
| masked_fields | list[str] | 被掩码的键路径清单，如 `["openai_compat.api_key"]`（客户端据此识别哪些回显值不可回传） |
| path | str | 配置文件路径（`~/.aife/config.yaml`，D13；本文保留的附加展示字段） |

**脱敏规则（硬规则，v1.1 对齐 04-data-model.md §6.1/§6.2）**：

1. `openai_compat.api_key` **恒返回 `"***"`**（无论其值为 `${VAR}` 引用、空串或异常明文——排查环境变量名请用 `aife doctor` 的 config 检查项）；
2. `network.proxy` 值形如 `http(s)://user:pass@host…` → userinfo 段掩码为 `http(s)://***:***@host…`（条件敏感字段）；
3. 其余字段原样返回；
4. 凡被掩码的键路径必须出现在 `masked_fields`。

#### 2.5.2 PATCH /api/config

**请求体** `ConfigPatch`：部分嵌套 dict（仅传需改动的节），pydantic 全量配置模型 all-optional 化后 merge。字段级校验规则（类型/enum/范围）以 04-data-model.md §2.1 各表「校验规则」列为权威。

| 校验/步骤 | 失败时 |
|---|---|
| ① 只接受部分键体（未传的节不动） | — |
| ② 顶层键 ∈ `config_version,hardware,ollama,models,backends,server,openai_compat,network,setup,bench,logging` | 400 CONFIG_INVALID，`details.unknown_top_level:[...]` |
| ③ **只读字段**：`config_version`、`hardware.vram_gb`（探测回填的展示位） | **400 CONFIG_READONLY**（v1.1 新增码），`details.fields` 列出只读键 |
| ④ 各节 pydantic 校验 | 400 CONFIG_INVALID，`details.fields:[{path,msg}]` |
| ⑤ `openai_compat.api_key` 只接受 `${VAR}`/`${VAR:-default}` 形式、空串、或哨兵值 `"***"`（=保持原值，GET 恒掩码下的回显兼容例外，见 §14-T11）；其余明文一律拒绝 | 400 CONFIG_INVALID |
| ⑥ 跨字段校验（04 §2.1.10）：`server.port≠ollama.port`；`mirror=custom` 时 `mirror_urls` 非空；`fallback` 元素 ∈ 已注册后端 | 400 CONFIG_INVALID，`details.fields` 指出冲突对 |
| ⑦ 变更涉及 `server.host/server.port` | **409 CONFIG_RESTART_REQUIRED**，`details.fields:["server.port"]`（监听地址不可热切换，需重启 serve） |
| ⑧ 其余变更 | 进入提交序列 |

**提交序列（原子性 + 回滚语义）**：

```
校验通过 → 原子写盘（tmp + fsync + os.replace；写前备份 config.yaml.bak，04 §3.1）
        → runtime.reload()（mtime+sha256 双检变更；内存热切换，不重启 aife-server）
        → [派生 env 有差异且 Ollama=managed] 触发 Ollama 子进程重启 + 广播 health.changed
        → 返回 200 新 ConfigView
```

- reload 抛异常 → **回滚**：恢复 `.bak` 字节 + 恢复内存旧配置对象 → **500 CONFIG_RELOAD_FAILED**（`details.field` 尽可能指出）。即：**校验失败即拒绝且不落盘（先验后写）；落盘后 reload 失败可完整回滚**。
- **热切换语义（逐键口径以 04-data-model.md §2.1「热切换」列为权威；API 侧行为映射）**：

| 热切换值 | API 行为 |
|---|---|
| 热生效 | reload 后立即（如 `models.default`、`backends.active`、`network.*`、`openai_compat.*`、`ollama.autostart`） |
| 需重启 Ollama | 自动重启 managed 子进程（aife-server 不动）+ 广播 health.changed；adopted → WARNING「下次重启生效」 |
| 需重启 aife-server | 仅 `server.host/port` → 409 CONFIG_RESTART_REQUIRED |
| 下次运行/下次 setup 生效 | 接受写入，当前进程不动作（如 `ollama.executable`、`setup.skip`、`logging.*`） |
| 只读 | 写入 → 400 CONFIG_READONLY |

- **并发**：PATCH 经 `asyncio.Lock` 串行；GET 可并发。
- **幂等**：同一 PATCH 重复提交结果一致（写相同值）。

### 2.6 GET /api/models（已装列表，US4.2）

**响应 200** `ModelList{models:list[ModelInfo]}`；`ModelInfo{name:str, size:int(字节), family:str, parameter_size:str, quantization:str, modified_at:datetime}`（映射 Ollama `/api/tags`；缺失字段给空串）。

- **错误码**：503 OLLAMA_UNAVAILABLE。
- **并发**：只读可并发。

### 2.7 GET /api/models/available（推荐目录，US4.4/D8）

- **查询参数**：`device_profile: str = null`（枚举 `cuda/rocm/xpu/mps/directml/npu/amd_rocm/cpu`；缺省用当前剖面）。
- **响应 200** `CatalogList{models:list[CatalogEntry]}`；`CatalogEntry{name:str, size_gb:float, min_ram_gb:float, tags:list[str], recommended_for:list[str]}`（静态 catalog 按剖面过滤；分档表遵循 D8）。
- **错误码**：400 VALIDATION（`device_profile` 非法值，`details.allowed:[...]`）。
- **语义**：纯静态规则表，**不调 LLM**（LLM 辅助推荐降级不影响本端点，§5 人机边界）。

### 2.8 POST /api/models/pull（异步拉取，US4.1）

- **请求体** `PullIn{name:str}`：`min_length=1, max_length=200, pattern=^[A-Za-z0-9._:-]+(/[A-Za-z0-9._:-]+)?$`（允许 `repo:tag` 与 `library/repo:tag`）。
- **响应 202** `PullTask{task_id:str, model:str, status:"queued"}`；随后进度经 WS `model.pull_progress`，完成经 `model.pull_done`（§4.5）。
- **错误码**：
  - 400 MODEL_INVALID_NAME（格式不符，`details.name`）；
  - 409 PULL_IN_PROGRESS（**全局单任务**：`models.max_concurrent_pull=1`，任何在飞任务都拒绝；`details{task_id, model, status}`——与架构 §4 配置对齐，§13-6）；
  - 503 OLLAMA_UNAVAILABLE。
- **并发与幂等**：内存态任务表 `dict[model_name → PullTask]`；同模型重复拉取 → 409 并**回显原 task_id**（客户端可转而订阅原任务，等价幂等）；拉取失败任务从表移除（可重试）。
- **流式进度**：Ollama `/api/pull` NDJSON 逐行 → 节流为每 200ms 或每 5% 一个 WS 事件（防事件洪水）。

### 2.9 DELETE /api/models/{name}（删除，US4.2）

- **路径参数**：`name: str`（**FastAPI 转换器 `{name:path}`**——模型名含 `:`；含 `/` 的 `library/model` 形态客户端须 `encodeURIComponent`，`/` 编为 `%2F`）。
- **响应 200** `DeleteResult{deleted:true, name:str}`（调 Ollama `/api/delete`）。
- **错误码**：404 MODEL_NOT_FOUND（`details{name, installed:[...]}`—— installed 列表帮助客户端自纠）；503 OLLAMA_UNAVAILABLE。
- **幂等**：二次删除 → 404 MODEL_NOT_FOUND（可接受的重放语义，非 500）。

### 2.10 POST /api/chat（非流式对话，US5.1/A5）

**请求体** `ChatIn`：

| 字段 | 类型 | 必填 | 默认 | 校验 |
|---|---|---|---|---|
| model | str \| null | 否 | null → 取 `models.default`，仍空则 catalog 按剖面推荐 | 同 MODEL_NAME_RE；指定时须已安装（否则 404） |
| messages | list[`ChatMessage`] | 是 | — | 1–100 条；`role ∈ system/user/assistant`；`content` 1–32000 字符；**至少一条 user** |
| options | `ChatOptions` \| null | 否 | null → 用配置默认 | 见下 |

`ChatMessage{role: Literal["system","user","assistant"], content: str}`。
`ChatOptions{temperature: float\|null ∈[0,2], top_p: float\|null ∈(0,1], max_tokens: int\|null ∈[1,32768], stop: list[str]\|null}`（映射 Ollama options：temperature/top_p/num_predict/stop）。

**响应 200** `ChatOut{message: ChatMessage(role=assistant), model: str, backend: str, usage: Usage, done: true}`；`Usage{prompt_tokens:int, completion_tokens:int, total_tokens:int}`（来自 Ollama 响应；Ollama 不给 usage 时以 0 填充并在日志标注 `usage_estimated=false`）。

**错误码（按判定顺序）**：

| 顺序 | code | HTTP | 触发 |
|---|---|---|---|
| 1 | VALIDATION | 400 | messages 空/无 user/角色非法/options 越界 |
| 2 | MODEL_NOT_FOUND | 404 | 指定 model 未安装（details 带 installed） |
| 3 | BACKEND_UNHEALTHY | 503 | 当前后端不可达或缺模型（`details.last_errors` 带回退链失败原因，US5.4） |
| 4 | MODEL_NOT_LOADED | 503 | 无任何可用模型（默认模型缺失且未指定） |
| 5 | UPSTREAM_TIMEOUT | 504 | 超过 `chat.request_timeout_s`（默认 300s） |

- **超时与重试**：httpx read timeout = `chat.request_timeout_s`；**不重试生成**（生成非廉价幂等操作；仅连接失败重试 1 次，退避 1s）。
- **并发**：不设应用层串行（Ollama 内部排队；`max_loaded_models=1` 时并发请求会排队加载模型，TTFT 抖动——bench 观察后决定是否加锁，§14）。
- **成本记录**：每次成功调用写 JSONL 日志 `event=chat.done`（backend/model/prompt_tokens/completion_tokens/duration_ms/trace_id），落 `~/.aife/logs/aife.log`（§9）。

### 2.11 POST /api/chat/stream（SSE 流式，US5.3）

- **请求体**：同 `ChatIn`；请求头 `Accept: text/event-stream`。
- **预检（同步，失败即普通 JSON 错误体，不进 SSE）**：同 §2.10 顺序 1–4。
- **流行为**：事件序列 `start → delta* → usage → done`；流中断自动降级与断连取消语义见 **§5**。
- **错误码**：预检同上；流中以 `error` 事件承载（§5.3）。

### 2.12 GET /api/backends（US5.4）

**响应 200** `BackendList`：

| 字段 | 类型 | 说明 |
|---|---|---|
| active | str | 当前后端名 |
| chain | list[str] | 回退链（active 优先 + `backends.fallback` 去重） |
| backends | list[`BackendInfo`] | 已注册后端元信息 |
| health | dict[str, `BackendHealth`] | 各后端健康（**pydantic**，修正 octop `h.__dict__` 缺陷） |

`BackendInfo{name, type: "ollama"\|"openai_compat", model: str\|null, base_url: str, api_key_configured: bool\|null}`（末字段仅 openai_compat 有意义，ollama 为 null）。
`BackendHealth{name: str, healthy: bool, detail: str}`（ollama 后端的 health 含「缺模型判不健康」）。

- **并发**：health 探测 `asyncio.gather`，单后端超时 3s；探测失败 → `healthy=false, detail=错误摘要`（不 500）。
- **错误码**：500 INTERNAL_ERROR（兜底）。

### 2.13 POST /api/backends/select（切换，原子性见 §8）

- **请求体** `BackendSelectIn{name: str, force: bool = false}`。
- **响应 200** `BackendSelectOut{active: str}`。
- **错误码**：400 BACKEND_UNKNOWN（`details{name, available:[...]}`）；503 BACKEND_UNHEALTHY（目标不健康；`force=true` **豁免**健康检查，details 附警告，供排障强切）。
- **幂等**：选择已在任的后端 → 200 原样返回（无副作用）。
- **原子性序列**：校验名 ∈ 已注册 →（非 force）健康检查 → **先持久化** `backends.active` 落盘（原子写）→ 换注册表指针（锁内单次赋值）→ 广播 `backend.changed`。持久化失败 → 500 且**不换指针**。

### 2.14 POST /api/setup/run（异步部署，US1.1）

- **请求体** `SetupRunIn{steps: list[str]\|null, skip: list[str]\|null}`：`steps/skip` 元素 ∈ `deps,ollama,model,verify`；`steps=null` → 全量四阶段；`skip` 显式跳过（等价 CLI `--skip-*`，US1.2）；**空列表 steps → 400 STEP_INVALID**（避免无意义 run）。
- **响应 202** `SetupRunOut{run_id: "run-<12位hex>", status: "running"}`；进度经 WS：`setup.started → setup.step_progress* → setup.step_done* →`（失败时 `setup.error` + 终止）。
- **错误码**：400 STEP_INVALID（`details{unknown:[...], allowed:[...]}`）；409 SETUP_RUNNING（`details{run_id, current_step}`——单实例锁，§8）。
- **幂等**：无客户端幂等键（本地单用户，run_id 即关联句柄）；重复提交被 409 拦截而非产生第二 run。
- **说明**：v1 **无取消端点**；CLI 侧 Ctrl-C 可中断（§14 待确认是否补 `DELETE /api/setup/run`）。

### 2.15 GET /api/setup/status

**响应 200** `SetupStatus{run_id: str\|null, status: "idle"\|"running"\|"done"\|"error", steps: list[SetupStep], current: str\|null}`；`SetupStep{name, status: pending/running/done/skipped/error, started_at, finished_at, duration_ms, error: ErrorBody\|null}`。

- **404 SETUP_NOT_FOUND 的精确定义**：进程启动后**从未运行过** setup 才 404；只要跑过一次，后续恒返回**最近一次** run（内存态，进程退出即重置——架构 §7；多 run 历史需持久化时联动 C-1，§14）。
- **并发**：只读可并发。

### 2.16 POST /api/ollama/restart（运维动作）

- **请求体**：无。
- **响应 200** `RestartOut{restarted: true, ollama_version: str}`。
- **行为**：managed → 停+按当前 env 重拉+就绪等待（**总预算 30s**）；未运行且 autostart=true → 等同 `ensure_running` 启动；**adopted → 409 OLLAMA_NOT_MANAGED**（`details{host, port}`——不重启外来进程，§1.4 同规则）；启动失败 → 503 OLLAMA_UNAVAILABLE。
- **并发**：与看门狗经 `restarting` 状态互斥（防双启）；进行中的 chat 请求将失败（503/连接错），客户端可重试。

### 2.17 OpenAI 兼容面（**本文新增**，理由见 §13-1）

需求 US5.1 与验收 A4 的验证命令直接使用 `/v1/models` 与 `/v1/chat/completions`，架构 §5.2 路由表未含——本文补全为正式契约。该面与 `/api/*` **共享** BackendRegistry 与降级策略，仅信封格式不同。

#### 2.17.1 GET /v1/models

**响应 200**：`{"object":"list","data":[{"id":"qwen2.5:3b","object":"model","created":1735689600,"owned_by":"ollama"}]}`（映射 `/api/tags`）。
**错误**：503 OLLAMA_UNAVAILABLE（OpenAI 信封，§2.17.4）。

#### 2.17.2 POST /v1/chat/completions（非流式）

**请求体**：OpenAI 形状 `{model:str, messages:[{role,content}], temperature?, top_p?, max_tokens?, stop?}`（字段校验同 §2.10 收紧：`role ∈ system/user/assistant`）。
**响应 200**：

```json
{
  "id": "chatcmpl-<hex>", "object": "chat.completion", "created": 1735689600,
  "model": "qwen2.5:3b",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "你好"}, "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
}
```

#### 2.17.3 POST /v1/chat/completions（stream=true → SSE）

OpenAI chunk 序列：`data: {"id":...,"object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}` → 内容 chunk（`delta:{content}`）→ 末 chunk（`delta:{}` + `finish_reason`）→ `data: [DONE]`。15s 注释心跳同 §5.4。

**与 /api/chat/stream 的差异（显式）**：OpenAI 面**不做**流中自动降级（OpenAI 客户端无法解释 degrade 语义，且全量重发会与已收片段重复）——流中失败 → OpenAI 错误 chunk + `[DONE]`。原生面（Web UI 用）保留降级（§5.5）。

#### 2.17.4 /v1/* 错误信封（偏离统一体，需主理人确认，§13-13）

```json
{"error": {"message": "model 'qwen2.5:7b' is not installed", "type": "invalid_request_error", "code": "MODEL_NOT_FOUND"}}
```

`code` 仍为 DOMAIN_REASON（§3 全集）；HTTP 状态码映射不变；`type ∈ invalid_request_error/not_found/server_error/upstream_error`。**理由**：US5.1 要求「OpenAI 兼容」，官方 SDK 只认 OpenAI 错误形状；`code` 字段保证机器可读性不丢失。trace_id 经 `X-Trace-Id` 头传递。

### 2.18 共享 pydantic 模型清单（`server/schemas.py` 骨架）

```python
class ErrorBody(BaseModel):            # 统一错误体核心；HTTP/WS/SSE 三通道复用
    code: str                          # DOMAIN_REASON，见 §3
    message: str                       # 人读文案，不稳定，客户端不得解析
    details: dict[str, Any] | None = None
    trace_id: str
class ErrorResponse(BaseModel):        # HTTP 错误响应外壳
    error: ErrorBody

class HealthLiveness(BaseModel):  status: Literal["ok"]; version: str; uptime_s: float
class CheckResult(BaseModel):     name: str; ok: bool; detail: str = ""; duration_ms: float = 0
class HealthChecks(BaseModel):    aife/ollama/models/backend/disk: CheckResult   # 五个固定子项
class HealthReport(BaseModel):    healthy: bool; checks: HealthChecks; checked_at: datetime

class SystemInfo(BaseModel):      version/platform/python/ollama_version/profile/active_backend: str
class EvidenceLevel(str, Enum):   E0="E0"; E1="E1"; E2="E2"; E3="E3"
class DeviceType(str, Enum):      cuda/rocm/xpu/mps/directml/npu/cpu
class DeviceInfo(BaseModel):      type: DeviceType; name: str; vram_gb: float|None; evidence: EvidenceLevel; detail: str=""
class ProfileInfo(BaseModel):     key/vendor/ollama_accel: str; env: dict[str,str]; caveats: list[str]=[]
class HardwareReport(BaseModel):  devices: list[DeviceInfo]; profile: ProfileInfo; source: EvidenceLevel

class ConfigView(BaseModel):      config_version: int; values: dict[str,Any]; path: str

class ModelInfo(BaseModel):       name/size/family/parameter_size/quantization/modified_at
class ModelList(BaseModel):       models: list[ModelInfo]
class CatalogEntry(BaseModel):    name/size_gb/min_ram_gb/tags/recommended_for
class CatalogList(BaseModel):     models: list[CatalogEntry]
class PullIn(BaseModel):          name: str = Field(min_length=1, max_length=200, pattern=MODEL_NAME_RE)
class PullTask(BaseModel):        task_id: str; model: str; status: Literal["queued","pulling","verifying","done","error"]
class DeleteResult(BaseModel):    deleted: bool = True; name: str

class ChatMessage(BaseModel):     role: Literal["system","user","assistant"]; content: str = Field(min_length=1, max_length=32000)
class ChatOptions(BaseModel):     temperature: float|None=Field(None,ge=0,le=2); top_p: float|None=Field(None,gt=0,le=1)
                                  max_tokens: int|None=Field(None,ge=1,le=32768); stop: list[str]|None=None
class ChatIn(BaseModel):          model: str|None=None; messages: list[ChatMessage]=Field(min_length=1,max_length=100); options: ChatOptions|None=None
class Usage(BaseModel):           prompt_tokens/completion_tokens/total_tokens: int
class ChatOut(BaseModel):         message: ChatMessage; model: str; backend: str; usage: Usage; done: bool=True

class BackendHealth(BaseModel):   name: str; healthy: bool; detail: str=""     # pydantic（修正 octop 缺陷）
class BackendInfo(BaseModel):     name/type/base_url: str; model: str|None; api_key_configured: bool|None=None
class BackendList(BaseModel):     active: str; chain: list[str]; backends: list[BackendInfo]; health: dict[str,BackendHealth]
class BackendSelectIn(BaseModel): name: str; force: bool=False
class BackendSelectOut(BaseModel): active: str

class SetupRunIn(BaseModel):      steps: list[str]|None=None; skip: list[str]|None=None
class SetupRunOut(BaseModel):     run_id: str; status: Literal["running"]="running"
class SetupStep(BaseModel):       name/status/started_at/finished_at/duration_ms/error(ErrorBody|None)
class SetupStatus(BaseModel):     run_id: str|None; status: Literal["idle","running","done","error"]; steps: list[SetupStep]; current: str|None

class RestartOut(BaseModel):      restarted: bool=True; ollama_version: str|None=None

# SSE 事件（§5）：SSEStart/SSEDelta/SSEUsage/SSEDone/SSEDegrade/SSEError(=ErrorBody)
# WS 信封（§4）：WSEvent{type,ts,seq,payload,trace_id?}
```

---

## 3. 错误码全集表

**处理链（全路由无裸 500，修正 octop 缺陷）**：

```
路由函数：领域异常 → 统一 raise AIEError(code, message, details=...)；禁止直接 raise HTTPException
   ↓
@app.exception_handler(AIEError)        → {code → HTTP} 映射 + ErrorResponse 序列化
@app.exception_handler(RequestValidationError) → 400 VALIDATION（不暴露 FastAPI 422 默认体）
@app.exception_handler(StarletteHTTPException) → 404→ROUTE_NOT_FOUND / 405→METHOD_NOT_ALLOWED / 其余按状态码套统一体
@app.exception_handler(Exception)       → 500 INTERNAL_ERROR；堆栈只进日志（logger.exception），响应只有 message
```

**状态码语义表（架构 §5.1 沿用 + 405 补充）**：

| 状态码 | 语义 | code |
|---|---|---|
| 400 | 参数/校验失败 | VALIDATION、CONFIG_INVALID、STEP_INVALID、MODEL_INVALID_NAME、BACKEND_UNKNOWN |
| 404 | 资源不存在 | MODEL_NOT_FOUND、SETUP_NOT_FOUND、ROUTE_NOT_FOUND |
| 405 | 方法不允许 | METHOD_NOT_ALLOWED |
| 409 | 状态冲突 | PULL_IN_PROGRESS、SETUP_RUNNING、CONFIG_RESTART_REQUIRED、OLLAMA_NOT_MANAGED |
| 429 | 限流 | RATE_LIMITED（**v1 保留未用**，§6.6） |
| 500 | 服务内部错误 | INTERNAL_ERROR、CONFIG_RELOAD_FAILED |
| 503 | 上游/依赖不可用 | OLLAMA_UNAVAILABLE、BACKEND_UNHEALTHY、MODEL_NOT_LOADED |
| 504 | 上游超时 | UPSTREAM_TIMEOUT |

**错误码全集**：

| code | HTTP | 触发条件 | message 模板 | details 结构 | 客户端应对 |
|---|---|---|---|---|---|
| VALIDATION | 400 | 请求体/查询参数 pydantic 校验失败 | `request validation failed: {n} field(s)` | `{fields:[{field,msg}]}` | 按 field 修正后重试 |
| CONFIG_INVALID | 400 | 配置 PATCH 校验失败/未知顶层键/version≠1 | `invalid config: {field}` | `{fields:[{path,msg}]}` 或 `{unknown_top_level:[...]}` | 修正配置字段 |
| STEP_INVALID | 400 | setup steps/skip 含未知阶段或 steps=[] | `unknown setup step(s): {names}` | `{unknown:[...], allowed:[...]}` | 用 allowed 内阶段名 |
| MODEL_INVALID_NAME | 400 | 模型名格式不符 MODEL_NAME_RE | `invalid model name: '{name}'` | `{name}` | 修正名称（`repo:tag`） |
| BACKEND_UNKNOWN | 400 | 后端名未注册 | `unknown backend: '{name}'` | `{name, available:[...]}` | 用 available 内名称 |
| MODEL_NOT_FOUND | 404 | 指定模型未安装（chat/delete） | `model '{name}' is not installed` | `{name, installed:[...]}` | 先 pull 或换模型 |
| SETUP_NOT_FOUND | 404 | 进程启动后从未运行 setup | `no setup run found` | `{}` | 先 POST /api/setup/run |
| ROUTE_NOT_FOUND | 404 | 路径不存在 | `route not found: {path}` | `{path}` | 检查 URL |
| METHOD_NOT_ALLOWED | 405 | 路径存在但方法不对 | `method not allowed: {method} {path}` | `{method, path, allowed:[...]}` | 改用 allowed 方法 |
| PULL_IN_PROGRESS | 409 | 已有拉取任务在飞（全局单任务） | `a pull task is already in progress` | `{task_id, model, status}` | 订阅该 task_id 的 WS 进度 |
| SETUP_RUNNING | 409 | setup 已在运行（单实例） | `a setup run is already in progress` | `{run_id, current_step}` | 轮询 /api/setup/status |
| CONFIG_RESTART_REQUIRED | 409 | PATCH 改 server.host/port | `config change requires serve restart` | `{fields:["server.port"]}` | 重启 aife serve 后再生效 |
| OLLAMA_NOT_MANAGED | 409 | 重启 adopted Ollama | `ollama process is not managed by aife` | `{host, port}` | 自行重启该 Ollama |
| RATE_LIMITED | 429 | （保留） | `rate limited` | `{retry_after_s}` | — |
| INTERNAL_ERROR | 500 | 未捕获异常兜底 | `internal server error` | `{}` | 带 trace_id 看日志/报 issue |
| CONFIG_RELOAD_FAILED | 500 | reload 失败（已回滚旧配置） | `config reload failed; previous config restored` | `{field?}` | 检查日志；旧配置仍生效 |
| OLLAMA_UNAVAILABLE | 503 | Ollama 不可达/未运行/重启失败 | `ollama is unavailable at {host}:{port}` | `{host, port, hint}` | `aife doctor` 定位 |
| BACKEND_UNHEALTHY | 503 | 后端不健康（含缺模型、回退链全败） | `backend '{name}' is unhealthy: {detail}` | `{name, detail, last_errors:[{backend,error}]}` | 换后端/拉模型/等恢复 |
| MODEL_NOT_LOADED | 503 | 后端无任何可用模型 | `no model available on backend '{name}'` | `{backend, expected_model}` | 先 pull 模型 |
| UPSTREAM_TIMEOUT | 504 | 上游超时（chat/流整体或空闲） | `upstream timeout after {timeout_ms}ms` | `{upstream, timeout_ms}` | 重试或换小模型 |

> WS/SSE 通道内的错误序列化为同构事件：WS `type:"error"` payload = ErrorBody；SSE `event: error` data = ErrorBody（架构 §5.1-1）。

---

## 4. WS /ws/events 契约

### 4.1 连接与鉴权

- URL：`ws://127.0.0.1:8189/ws/events`（随 `server.host/port`）。**无鉴权**（本地单用户，§6.1）。
- 单连接订阅**全量广播**（不区分主题）；连接建立即生成连接级 `trace_id`（后续事件信封携带）。
- 同源策略：本地页面直连；跨源场景受 CORS/浏览器 WS 同源规则约束（§6.2）。

### 4.2 事件信封（架构 §5.3 扩展 seq/trace_id）

```json
{ "type": "model.pull_progress", "ts": "2025-01-01T00:00:00Z", "seq": 42,
  "trace_id": "0f4b8c2e-...", "payload": { "task_id": "t-1", "completed": 1200000000, "total": 4700000000 } }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| type | str | 事件名（§4.5 表） |
| ts | datetime | 服务端发出时间（UTC） |
| seq | int | **每连接单调递增，从 1 开始**（新增字段，背压可观测的关键，§4.6） |
| trace_id | str \| null | 触发事件的请求 trace（无则 null） |
| payload | dict | 事件数据（§4.5） |

### 4.3 连接建立事件 hello（扩展）

连接 accept 后立即发送：

```json
{"type":"hello","ts":"...","seq":1,"payload":{"server_version":"1.0.0","active_backend":"ollama","latest_setup_run_id":"run-ab12cd34ef56"}}
```

用途：客户端确认协议就绪 + **断连重连后快速重同步**（无需回放历史，§4.4）。

### 4.4 心跳与重连规则

| 项 | 规则 |
|---|---|
| 应用心跳 | 服务端每 **30s**（`server.ws_heartbeat_s`，测试可配 1s）发 `{"type":"heartbeat","payload":{}}` |
| 协议心跳 | uvicorn WS ping/pong（默认 20s）双保险，检测半开连接 |
| 断连判定 | 客户端 90s 无 pong/心跳响应 → 服务端关闭（1011）并告警 |
| 重连策略 | 客户端指数退避 **1s→2s→4s→…→30s 封顶**，加 ±20% jitter；重连即收 hello 重同步 |
| 事件回放 | **不回放**。重连期间的进度/状态类事件，客户端用 REST 补齐（setup 进度 → GET /api/setup/status；健康 → GET /api/health/deep） |
| 服务端停机 | 广播 `server.shutdown{reason}` 后关闭码 **1001** |

### 4.5 事件表（payload 逐字段）

| 事件 | 触发时机 | payload 字段（类型/说明） |
|---|---|---|
| hello（扩展） | 连接建立 | `server_version:str, active_backend:str, latest_setup_run_id:str\|null` |
| setup.started | setup 流水线开始 | `run_id:str, steps:list[str]`（按执行序） |
| setup.step_progress | 阶段内进度 | `run_id:str, step:str, message:str, percent:float\|null`（percent 为可选扩展） |
| setup.step_done | 阶段完成 | `run_id:str, step:str, duration_ms:float` |
| setup.error | 阶段失败 | `run_id:str, step:str, code:str(DOMAIN_REASON), message:str, remedy:str`（remedy 为可复制命令，US6.3） |
| model.pull_progress | Ollama /api/pull 进度 | `task_id:str, model:str, status:str, completed:int(字节), total:int\|null` |
| model.pull_done | 拉取完成 | `task_id:str, model:str, size:int\|null` |
| log.line | 服务端日志镜像（受 log_level） | `level:str, logger:str, message:str, ts:datetime` |
| backend.changed | 后端切换/回退 | `active:str, reason:str`（回退时 reason 含 last_errors 摘要，US5.4） |
| health.changed | deep health 结论翻转（30s 轮询比对新旧） | `healthy:bool, failed_checks:list[str]` |
| error | 通道内错误 | `= ErrorBody{code,message,details,trace_id}` |
| backpressure（扩展） | 该连接发生丢帧且距上次通知 ≥5s | `dropped:int, queue_size:int` |
| server.shutdown（扩展） | 服务端停机 | `reason:str` |
| heartbeat | 30s | `{}` |

### 4.6 背压处理（**修正 octop 静默丢帧缺陷**：必须可观测）

| 规则 | 定义 |
|---|---|
| 队列 | 每连接独立 `asyncio.Queue(maxsize=256)`；广播 `put_nowait`，不阻塞生产者（拉取/部署流水线永不被慢客户端拖死） |
| 溢出策略 | **丢最旧 + 计数**：`dropped += 1`；`seq` 因此断号，客户端可检测 `seq` 不连续发现丢帧 |
| 通知 | 每次丢帧且距上次通知 ≥5s，向该连接补发 `backpressure{dropped,queue_size}` 事件（尽力而为，仍可能被后续丢帧淘汰） |
| 指标 | `ws_dropped_events_total`（进程计数器，随 `log.line`/ERROR 日志可观测）——**丢弃永不静默** |
| 熔断 | 单连接 60s 内 `dropped > 1000` → 服务端主动关闭，关闭码 **1011**，reason `slow_consumer`；客户端重连后由 hello + REST 重同步 |
| 客户端义务 | 发现 `seq` 断号或收到 backpressure → 立即 REST 补齐状态（setup/health），不得假装连续 |

---

## 5. SSE /api/chat/stream 契约

### 5.1 传输参数

| 项 | 值 |
|---|---|
| Content-Type | `text/event-stream; charset=utf-8` |
| 响应头 | `Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`（防反向代理缓冲，架构 §6 流式不全量缓冲） |
| 帧格式 | `event: <type>\ndata: <json 单行>\n\n` |
| 保活注释 | 15s 无数据发 `:ping\n\n`（代理/浏览器不断连） |
| 整体超时 | `chat.stream_timeout_s`（默认 600s） |
| 空闲超时 | `chat.stream_idle_timeout_s`（默认 120s，两片 delta 间隔） |

### 5.2 事件序列与 schema

```
start → delta* → usage → done            （正常）
start → delta* → error                   （流中失败且降级失败/不可降级）
start → delta* → degrade → delta+ → usage → done   （流中传输中断，降级非流式重试成功）
```

| 事件 | data schema | 字段说明 |
|---|---|---|
| start | `SSEStart` | `model:str, backend:str, request_id:str`（request_id 关联日志） |
| delta | `SSEDelta` | `content:str`——增量文本（UTF-8 可含换行；JSON 转义后单行） |
| usage | `SSEUsage` | `prompt_tokens/completion_tokens/total_tokens:int`（Ollama 末帧） |
| done | `SSEDone` | `done:true, finish_reason:"stop"\|"length", model:str`——**流终止信号**，服务端随后关闭响应 |
| degrade | `SSEDegrade` | `reason:str, from_mode:"stream", to_mode:"non-stream", attempt:1`——**本文新增扩展事件**（US5.3 降级的显式信号） |
| error | `SSEError` | `= ErrorBody{code,message,details,trace_id}`——流终止信号，随后关闭响应 |

客户端渲染规则（交颜可心）：收到 `degrade` → **重置已接收文本缓冲区**；后续 delta 为完整重生成内容（避免片段重复）。

### 5.3 中断语义（客户端断开 → 取消上游）

- 客户端断开（`http.disconnect` / `asyncio.CancelledError`）→ 服务端**立即** `aclose()` 到 Ollama 的 NDJSON 流（取消未完成生成，释放 Ollama 算力）→ 写日志 `event=chat.stream_cancelled{by:client}` → **不重试**（用户主动停止，已接收内容由前端保留，US5.3「中断后可继续」为客户端语义）。
- 服务端停机 → 进行中的流直接关闭（§1.4）。

### 5.4 流中错误的重试降级规则（继承需求 US5.3）

| 场景 | 行为 |
|---|---|
| 预检失败（400/404/503） | 不发 SSE，直接返回普通 JSON 错误体（§2.11） |
| 首 delta 前上游连接失败 | 直接 error 事件（BACKEND_UNHEALTHY/UPSTREAM_TIMEOUT），**不降级**（尚无增量内容，重试无副作用但按需求只降级一次——保持简单：仅在已产生增量后中断才降级） |
| 已产生增量后上游中断（网络错误/连接重置/上游 5xx，非用户断开） | **自动降级**：emit `degrade` → 以非流式重试同一请求（`chat.request_timeout_s` 预算，含 1 次连接重试）→ 成功：单条 delta 发完整文本 + usage + done；失败：error 事件（原错误码） |
| 空闲/整体超时 | error 事件 `UPSTREAM_TIMEOUT`（details 含 timeout_ms） |
| 指标 | `chat_stream_degraded_total` >0 记 WARNING 日志（降级是容错不是常态） |

> 降级仅一次（需求原文「重试一次」），不级联。

### 5.5 /v1/chat/completions 流式差异

见 §2.17.3：OpenAI chunk 格式 + `[DONE]` 终止；**无 degrade 事件**，流中失败 → OpenAI 错误 chunk + `[DONE]`。

---

## 6. 安全与边界

### 6.1 绑定策略（D10）

- 默认 `server.host=127.0.0.1`；`0.0.0.0` 可配但：启动时终端 + WARNING 日志双提示「服务将暴露到局域网，无鉴权，风险自担」；README 同述。**v1 不提供 token 鉴权**（架构 Won't have + §10.1 演进项）。
- 端口：`server.port=8189` ≠ `ollama.port=11434`（§4 校验）。

### 6.2 CORS（本地）

- `server.cors_origins` 默认 `["http://127.0.0.1:8189","http://localhost:8189"]`（本文新增配置键，§13-10）；`allow_methods=[GET,POST,PATCH,DELETE,OPTIONS]`；`allow_headers=[Content-Type,X-Trace-Id]`；`allow_credentials=False`。
- 同源静态托管是主路径，CORS 仅为开发/显式配置场景兜底。

### 6.3 密钥与敏感数据

- 密钥**只经 `${VAR}` 引用**，不落明文（架构 §4/§7）；GET /api/config 脱敏规则见 §2.5.1。
- `openai_compat.api_key` 解析后仅存在于内存，禁止进日志/错误体/WS/SSE。
- 日志脱敏：错误 message 与日志字段过滤 `api_key|secret|token|password` 模式的值（logging.py filter）。

### 6.4 trace_id 生成与传递

- 中间件为每个请求生成 `trace_id`（客户端可用 `X-Trace-Id` 头传入，格式 `^[A-Za-z0-9_-]{1,64}$`，非法则忽略并新建 uuid4 hex）。
- 出口：**所有响应头 `X-Trace-Id`**、错误体 `trace_id`、结构化日志 `trace_id`、WS 连接级 trace_id（事件信封携带）、SSE error 事件携带。三处一致（架构 §5.1-3）。
- **错误响应绝不泄露堆栈**：堆栈只进日志（`logger.exception`），响应只有 message（修正 octop `_unhandled` 直接回传 `str(exc)` 的行为）。

### 6.5 静态托管与路径穿越

- `web/` 挂 `/`；未知路径且 `Accept: text/html` → 返回 `index.html`（前端视图路由自理）；其余 → 404 ROUTE_NOT_FOUND 统一体。`StaticFiles` 自带 `..` 穿越防护；API 前缀（`/api` `/v1` `/ws`）绝不 fallback 到 HTML。

### 6.6 限流策略结论：**v1 不启用 429**

| 结论 | 理由 |
|---|---|
| 不加限流中间件 | 本地单用户（架构 §1.2），无滥用面；加限流=加依赖/加误判/加测试面，违反依赖预算 |
| 已有等效防护 | pull/setup 单实例 409 守卫（§8）；Ollama 自身串行推理 |
| 码位保留 | `RATE_LIMITED(429)` 定义但 v1 不触发；演进（0.0.0.0/多用户）时启用 |

---

## 7. 鉴权与权限

| 项 | v1 决策 | 理由 |
|---|---|---|
| 认证 | **无**（本地单用户工具） | 架构 Won't have「多租户鉴权」；D10 默认仅 127.0.0.1 |
| 权限模型 | 不适用（无 RBAC/ABAC） | 单用户即全部权限 |
| 会话 | 无服务端会话；WS/SSE 连接即身份 | 无状态最简 |

**越权防护点（无鉴权不等于无边界）**：

1. **配置注入**：`${VAR}` 展开白名单化——仅允许 `AIE_` 前缀环境变量（`AIE_OPENAI_BASE_URL/AIE_OPENAI_API_KEY/…`），任意环境变量引用拒绝（400 CONFIG_INVALID）；
2. **模型名注入**：MODEL_NAME_RE 严格白名单字符集，防路径穿越/参数注入 Ollama；
3. **路径穿越**：静态托管 §6.5；`{name:path}` 路由参数解码后仍过 MODEL_NAME_RE；
4. **进程边界**：OllamaManager 只操作自己拉起的子进程（adopted 不杀不重启，§1.4/§2.16）；
5. **信息泄露**：错误体/日志脱敏（§6.3/6.4）；`/api/config` 脱敏（§2.5.1）。

演进（架构 §10.1）：并发用户 >1 → `server.host=0.0.0.0` + token 鉴权 + 会话隔离，契约层预留 `Authorization: Bearer` 解析位（v1 收到该头忽略并记 DEBUG 日志）。

---

## 8. 异步与一致性（幂等与并发）

| 场景 | 机制 | 冲突表现 | 一致性级别 |
|---|---|---|---|
| 模型拉取防重 | 内存态任务表 + 全局单任务（`max_concurrent_pull=1`） | 409 PULL_IN_PROGRESS（回显原 task_id） | 进程内强一致；任务态不持久化（重启可重拉） |
| setup 单实例 | 内存态 run 锁 | 409 SETUP_RUNNING（details 带 run_id/current_step） | 进程内强一致；run 态不持久化 |
| 后端切换原子性 | `asyncio.Lock` + **先持久化后换指针**；换指针为锁内单次赋值 | 持久化失败 500 且不换；未知名 400 | 配置落盘（原子写）与内存指针最终一致；广播在换指针后 |
| 配置 PATCH 回滚 | 先验后写（校验失败不落盘）；原子写盘（tmp+fsync+rename，留 .bak）；reload 失败恢复 .bak + 内存旧对象 | 400 / 409 / 500 CONFIG_RELOAD_FAILED（旧配置仍生效） | 写盘原子；reload 失败可回滚 |
| chat 并发 | 无应用层锁（Ollama 内部排队） | 无冲突码；TTFT 可能抖动 | 最终一致（请求不丢） |
| ollama restart | `restarting` 状态与看门狗互斥 | 409 OLLAMA_NOT_MANAGED（adopted）；503（启动失败） | 状态机驱动，无双启 |
| deep health 轮询 | 30s 后台 task，结论翻转才广播 | 无 | 最终一致（探测即瞬时真相） |
| 事件广播 | 每连接有界队列，丢最旧 + seq 断号可观测 | backpressure 事件 / 1011 熔断 | 至少一次→有界丢失（可检测） |

**幂等设计总则**：本地单用户 + 无资金/订单/消息发送类接口，**不引入客户端幂等键**（`Idempotency-Key` 头部 v1 不识别，收到忽略并 DEBUG 日志）。等价保障：服务端状态守卫（409）+ 任务/运行句柄（task_id/run_id）供客户端关联与轮询。重复删除模型 → 404（可接受重放语义）。

---

## 9. 外部依赖治理

| 依赖 | 超时 | 重试 | 熔断 | 降级方案 | 成本记录 |
|---|---|---|---|---|---|
| **Ollama**（本地子进程/adopted） | connect 2s；chat 读 `chat.request_timeout_s`=300s；deep health 2s/项 | 仅连接失败重试 1 次（退避 1s）；生成/流**不重试**（§5.4 降级除外） | 看门狗 + deep health：连续 3 次探测失败 → 标记 unhealthy；30s 后半开恢复探测 | chat 503 BACKEND_UNHEALTHY + fallback 链（`backends.fallback`，外部 API 为 Should/D6）；流式降级非流式一次（§5.4） | `chat.done` 日志：backend/model/prompt_tokens/completion_tokens/duration_ms；`~/.aife/logs/aife.log` |
| **外部 OpenAI 兼容 API**（D6 接口预留，Should） | connect 5s；读 60s | 连接失败重试 1 次 | v1 不接熔断器（预留） | 本地 Ollama 为链首；外部仅在链中或显式切换时使用 | 同左（token 计费敏感，必须落日志） |
| Ollama 二进制安装（bootstrap） | 下载 10min | 分阶段重试（US1.2，`--skip-*`） | — | doctor 指引 + 手动安装步骤（D9：包管理器→官方脚本→手动指引） | 无（一次性安装） |

> 禁止裸调用：所有出站 HTTP 经 `ollama/protocol.py` 与 `backends/*` 统一客户端（httpx.AsyncClient，连接池），路由层不得自建客户端。

---

## 10. 可观测性

### 10.1 日志规范（JSONL，架构 §7）

- 落盘 `~/.aife/logs/aife.log`，滚动 10MB×5；控制台同步（级别 `server.log_level`）。
- 每条日志字段：`ts, level, logger, trace_id?, event, msg, duration_ms?` + 事件私有字段。
- 关键事件清单：`serve.ready / serve.shutdown / ollama.started / ollama.exited / ollama.restart_scheduled / chat.done / chat.stream_cancelled / chat.stream_degraded / chat.error / pull.started / pull.done / pull.error / config.reloaded / config.reload_failed / backend.switched / backend.fallback / health.changed / ws.client_connected / ws.slow_consumer / error.unhandled`。

### 10.2 链路追踪点

请求入口（TraceId 中间件）→ 路由 → registry/backend → Ollama 上游；Ollama 协议无 trace 头，以 `request_id`（chat/pull 任务句柄）在日志侧关联。WS 事件信封 `trace_id` 字段回填触发请求。

### 10.3 核心指标与告警阈值（进程内计数 + 日志可观测）

| 指标 | 类型 | 告警阈值 | 观测方式 |
|---|---|---|---|
| `ollama_up` | gauge 0/1 | 0 持续 >10s → ERROR + `health.changed` | deep health / 看门狗 |
| `http_requests_total{route,status_class}` | counter | 5xx 速率 >1/min → WARNING | 日志聚合 |
| `http_request_duration_ms{route}` | histogram | p95 >5s（非 chat 路由）→ WARNING | 日志 |
| `chat_tokens_total{backend,model}` | counter | —（成本观测，无告警） | `chat.done` 日志 |
| `ws_clients` | gauge | — | 连接/断开日志 |
| `ws_dropped_events_total` | counter | >0 → WARNING（丢帧非正常） | §4.6 |
| `chat_stream_degraded_total` | counter | >0 → WARNING | §5.4 |
| `pull_tasks_active` / `setup_runs_total{result}` | gauge/counter | — | 任务日志 |

> v1 不暴露 `/api/metrics`（Prometheus 格式）端点——本地单用户无采集方；指标经日志 + deep health 观测；端点列入演进（§13 不实现声明）。

### 10.4 健康探针

`/api/health`（liveness，进程级）/ `/api/health/deep`（readiness 语义，恒 200 + healthy 字段）——对应 US6.4 与需求 S-4（doctor 五类检查的服务侧子集）。

---

## 11. OpenAPI 导出方案

| 项 | 定义 |
|---|---|
| 自动生成 | FastAPI 原生 `/openapi.json`、`/docs`（Swagger UI）、`/redoc`；**全部响应模型 pydantic**（ADR-006），schema 完整可导出（含 HealthReport/BackendHealth——修正 octop 缺陷） |
| 导出命令 | **`aife openapi [--out PATH]`**（新增 CLI 子命令，§13-12）：`aife openapi > openapi.json`；默认输出到 `docs/api/openapi.json` |
| 文档落位 | `docs/api/openapi.json` + 本文档共同构成契约文档；README 指向 `/docs` |
| CI 卡点 | CI 增步骤：`python -m aife openapi --out docs/api/openapi.json && git diff --exit-code docs/api/openapi.json`——契约变更必须显式过审（防「代码改了契约没改」） |
| 版本化策略 | v1 路由**不带** `/api/v1` 前缀（架构 §10.1：多机管理时才引入）；破坏性变更走 §13 流程：新前缀 + 旧路由 deprecated 公告 |

---

## 12. 可验证结果清单（每条契约 → 测试方式；凌无缺直接采用）

| # | 契约 | 测试方式（无 GPU/Ollama/网络可跑，S7） | 对应需求/验收 |
|---|---|---|---|
| V1 | 统一错误体 + 无裸 500 | `test_server_api.py`：TestClient 参数化遍历全路由注入失败（mock runtime），断言 body 符合 `{error:{code,message,details,trace_id}}`；路由内抛裸 Exception → 500 INTERNAL_ERROR 统一体（非 FastAPI 默认体） | ADR-006；修正 octop |
| V2 | X-Trace-Id 三处一致 | 任意错误响应：`body.error.trace_id == headers["X-Trace-Id"]`；自定义合法头被沿用 | 架构 §5.1-3 |
| V3 | 422→400 VALIDATION | POST /api/chat 空 messages → 400 VALIDATION（**不是** 422/FastAPI 默认体） | §3 |
| V4 | 404/405 统一体 | GET /api/nope → 404 ROUTE_NOT_FOUND；POST /api/health → 405 METHOD_NOT_ALLOWED | 修正 octop |
| V5 | health liveness/deep | TestClient 200 + status=ok；mock Ollama 宕（httpx **MockTransport** 抛连接错）→ deep 恒 200 且 `healthy=false, checks.ollama.ok=false` | US6.4/A2 |
| V6 | 缺模型判不健康 | mock /api/tags 返回空列表 → deep `checks.backend.ok=false`；`/api/backends` health 对应项 unhealthy | M14 教训/US5.4 |
| V7 | config 脱敏 | 配置含明文 api_key → GET 返回 `"***"`；`${VAR}` 引用原样 | §2.5.1 |
| V8 | config PATCH 三态 | 非法值 → 400 且文件未改（先验后写）；改 server.port → 409 CONFIG_RESTART_REQUIRED；reload 失败（mock 抛错）→ 500 且旧配置恢复 | ADR-003 |
| V9 | pull 防重 409 | 连发两次 POST /api/models/pull → 第二次 409 PULL_IN_PROGRESS，details.task_id 与首次一致 | 架构 §1.4 链路 C |
| V10 | pull 进度事件 | MockTransport 吐 NDJSON 进度 → WS 收 `model.pull_progress`（节流后）→ `model.pull_done`，seq 连续 | US4.1 |
| V11 | setup 单实例 409 | 并发两次 POST /api/setup/run → 409 SETUP_RUNNING；status 端点步骤态流转断言 | US1.1 |
| V12 | setup 404 语义 | 进程启动未 run → GET status 404 SETUP_NOT_FOUND；run 一次后恒 200 | §2.15 |
| V13 | chat 非流式全字段 | MockTransport `/api/chat` → ChatOut 五字段 + usage；未装模型 → 404 且 details.installed 正确 | A5/US5.1 |
| V14 | chat 流式事件序列 | `stream=True` 消费 → `start,delta+,usage,done` 严格有序；`X-Accel-Buffering: no` 头存在 | US5.3 |
| V15 | 流中降级一次 | mock 首个 delta 后连接重置 → 收 `degrade` → 完整 delta → done；重试仍败 → error 事件（原 code） | US5.3 |
| V16 | 客户端断连取消上游 | mock transport 记录 `aclose()` 被调用（无重试、无 done） | US5.3 |
| V17 | backend 切换原子性 | 未知名 400（details.available）；目标不健康 503；force=true 200；重复选同一后端幂等 200 | US5.4 |
| V18 | OpenAI 兼容面 | `/v1/models` 200 含默认模型 id；`/v1/chat/completions` 结构 + usage + stream chunk 序列 + `[DONE]`；错误为 OpenAI 信封且 code=DOMAIN_REASON | US5.1/**A4** |
| V19 | WS 背压可观测 | 队列 maxsize=1 + 批量灌事件 → `ws_dropped_events_total>0`、收到 backpressure 事件或 seq 断号（二者至少其一，**禁止静默**） | 修正 octop 丢帧 |
| V20 | WS 心跳 | 测试配置 `ws_heartbeat_s=1` → 1.5s 内收 heartbeat；断链重连收 hello | 架构 §5.3 |
| V21 | OpenAPI 导出 | `aife openapi` 生成 JSON：无悬挂 `$ref`；HealthReport/BackendHealth 有完整 schema（回归守护 octop 缺陷） | ADR-006 |
| V22 | 启动/退出序列 | mock subprocess：serve 启动 → ensure_running 顺序调用断言；SIGTERM → managed Ollama 收到 terminate、adopted 不杀；`shutdown_on_exit=false` 保留 | §1.3/§1.4 |
| V23 | 崩溃守护 | mock Ollama 进程退出 → 5s/10s/15s 三次重拉断言 → 3 次全败 → unhealthy + doctor 检查项检出 | 架构 §6/US6.1 |

---

## 13. 与架构文档的不一致与补充（显式修正清单）

| # | 架构原文 | 本文决策 | 理由 |
|---|---|---|---|
| 1 | §5.2 路由表无 `/v1/models`、`/v1/chat/completions` | 补全为正式契约（§2.17） | 需求 US5.1 与**验收 A4 的命令直接用这两个路径**；架构表遗漏将导致必过验收无契约可依 |
| 2 | §5.1 状态码表无 405 | 补 `METHOD_NOT_ALLOWED(405)` | FastAPI 默认 405 返回 `{"detail":...}`，破坏统一错误体 |
| 3 | §5.1 未规定 pydantic 校验失败（422）映射 | 统一转 **400 VALIDATION** | 架构状态码表将 VALIDATION 归 400；保持全站错误体一致 |
| 4 | §5.2 /api/config PATCH 错误码仅 400 | 补 409 CONFIG_RESTART_REQUIRED、500 CONFIG_RELOAD_FAILED | host/port 不可热切换需明确拒绝；reload 失败需可回滚语义（ADR-003 后果） |
| 5 | §5.2 /api/ollama/restart 错误码仅 503 | 补 409 OLLAMA_NOT_MANAGED | adopted 进程不重启（§1.4 规则）需显式错误码 |
| 6 | §5.2 pull 409 语义偏「同模型防重」 | 定为**全局单任务** 409 | 与架构 §4 `models.max_concurrent_pull=1` 对齐 |
| 7 | §5.3 WS 信封 `{type,ts,payload}` | 增 `seq`（每连接单调递增）与 `trace_id` | seq 断号使丢帧可检测（修正 octop 静默丢帧）；trace_id 满足架构 §5.1-3 链路关联 |
| 8 | §5.3 事件表 11 项 | 增 `hello`、`backpressure`、`server.shutdown`（扩展事件） | 重连重同步、背压可观测、优雅停机通知；前端不识别时可忽略（信封兼容） |
| 9 | §5.2 /api/chat/stream 错误仅「同上」 | §5 定义流中 error 事件、degrade 降级、断连取消、双超时 | US5.3「中断后自动降级重试一次」需要契约级事件语义 |
| 10 | §4 配置项表 | 补 `ollama.shutdown_on_exit=true`、`chat.request_timeout_s=300`、`chat.stream_timeout_s=600`、`chat.stream_idle_timeout_s=120`、`server.cors_origins=[...]`、`server.ws_heartbeat_s=30` | 进程模型/SSE/WS/CORS 落地必需；均有默认值，不破坏既有键 |
| 11 | §2 目录无 SSE 编解码模块 | 增 `aife/server/sse.py` | 事件序列化 + 15s 保活 + 缓冲头集中治理 |
| 12 | §5.4 CLI 表 8 子命令 | 增 `aife openapi`（第 9 个） | §11 导出方案需要入口；不影响既有命令 |
| 13 | §5.1 要求全站统一错误体 | `/v1/*` 用 OpenAI 信封（code 仍 DOMAIN_REASON） | US5.1「OpenAI 兼容」优先；SDK 客户端不认自定义信封。**列待确认请主理人确认** |
| 14 | §5.2 /api/setup/status 404 条件未定义 | 定义为「进程启动后从未 run 过」；只保留最近一次 run | 与架构 §7「运行时状态内存态、进程退出即重置」自洽 |

---

## 14. 风险与待确认

| # | 类型 | 内容 | 影响 | 对策/责任 |
|---|---|---|---|---|
| T1 | 待确认 | §13-13：`/v1/*` 错误信封偏离统一体 | 契约一致性 vs SDK 兼容 | 建议采纳（兼容优先，code 不丢失）；请主理人确认 |
| T2 | 待确认 | `/v1/chat/completions` 是否与 `/api/chat` 同里程碑交付 | A4 验收命令直接用 `/v1/models` | 建议 M3 同步交付（薄封装，边际成本低） |
| T3 | 待确认 | deep health 磁盘阈值：<5GB 失败 / <10GB 警告（本文定值） | 低端机误报 | 请 PM 按 P1 画像（≥20GB 空闲假设，R5）确认 |
| T4 | 待确认 | setup 无取消端点（v1） | 长部署（拉模型）无法中止 | CLI Ctrl-C 可中断；API 取消列入 Could |
| T5 | 待确认 | chat 无应用层并发锁 | `max_loaded_models=1` 时并发 TTFT 抖动 | bench（D15）观测后决定；契约已留 error 语义 |
| T6 | 待确认 | `/api/hardware` 无强制重探测端点 | 热插拔 GPU 场景 | CLI `aife detect` 覆盖；API 重探测列入演进 |
| T7 | 风险 | SSE 未来套反向代理被缓冲 | 流式变「一次性返回」 | 已加 `X-Accel-Buffering: no`；部署文档注明勿缓冲 |
| T8 | 风险 | setup/status 仅存最近一次 run（内存态） | 前端多 run 历史诉求 | 联动 C-1（SQLite）时持久化 |
| T9 | 风险 | WS seq 断号依赖客户端自觉补齐 | 慢客户端状态漂移 | backpressure 事件 + 1011 熔断双保险；前端义务写入 §4.6 |
| T10 | 风险 | 外部 API 回退链（D6）若 M3 延期 | fallback 只有单后端 | 接口/契约已预留（BackendInfo/chain/last_errors），实现可后补 |

---

—— 程不宕（后端服务工程师），Phase 2 服务侧交付完毕。契约自洽性声明：本文全部字段名/错误码与架构 §5 一致；14 处差异/补充均在上表显式列明并给出理由，无隐式偏离。
