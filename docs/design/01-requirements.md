# AI For Everyone（AIE）需求定义 v0.1

> **文档定位**：Phase 1 需求侧唯一权威输入，落盘至 `docs/design/01-requirements.md`，供 Phase 2 架构/服务/前端/测试专项设计直接引用。
> **需求来源**：主理人原始需求 6 条（逐条覆盖，见 §1.6 映射表）+ 参考实现 Octop（`C:/Users/DELL/WorkBuddy/rea/octop`）逆向设计基因。
> **验证环境诚实声明（贯穿全文的硬约束）**：本机为 Windows / Intel Core Ultra 7 265K（20 核 / 95.5GB RAM）/ **无 NVIDIA GPU / 未装 Ollama**。因此 AIE 的 **CPU 路径必须真实验证**；GPU / NPU / AMD / Apple 路径只允许契约级验证（mock 探测输出 → 断言剖面与启动参数），任何文档不得把契约验证写成实测结论。

---

## 1. 问题定义

### 1.1 产品一句话定义

**AI For everyone（AIE）= 一条命令，把任意电脑（GPU/NPU/CPU）变成可用的本地 AI 工作站：自动探测硬件 → 自动安装并配置 Ollama（含加速路径）→ 自动拉取并验证模型 → 本地对话服务即刻可用。**

产品形态：Python 包（`aife`）+ CLI（`aife setup / doctor / serve / detect / models / chat`）+ FastAPI 服务（OpenAI 兼容 API）+ 零构建浏览器前端。分发形态：三分平台压缩包 + 可直接上传 GitHub 的压缩包。

### 1.2 成功标准（可度量，均给出度量命令或观测点）

| # | 成功标准 | 度量方式 / 命令 | 目标值 | 前提假设 |
|---|---|---|---|---|
| S1 | 单条命令从零到首次本地推理成功 | 冷启动机执行 `aife setup && aife serve`，计时至 `aife chat "你好"` 返回首个非空回复 | **CPU 路径 ≤ 15 分钟**（3B 模型）；国内网络下拉 7B 模型单阶段 ≤ 20 分钟 | ≥8GB RAM、≥20GB 空闲磁盘、100Mbps 网络 |
| S2 | 一键部署一次跑通率 | 统计 setup 退出码=0 且 serve 后 `/v1/models` 探针 200 的比例（setup JSONL 日志） | 支持矩阵内 ≥ 90% | 支持矩阵见 §3.1 |
| S3 | 设备检测正确率 | `aife detect --json` 输出设备类型 vs 实际硬件抽检比对；每条结论带 E0–E3 证据等级 | 支持矩阵内 **100%**，无证据等级输出视为不合格 | 探测失败必须降级 CPU + 显式警告，不得静默 |
| S4 | doctor 体检时效与覆盖 | `time aife doctor`；核对常见失败模式清单（网络/端口占用/磁盘不足/驱动缺失/Ollama 版本/模型损坏） | 30 秒内完成；常见失败模式覆盖率 ≥ 95% | doctor 在裸机（无 Ollama）不崩溃 |
| S5 | 推理可用性与延迟 | `aife chat "你好，请用一句话介绍你自己"` | 首 token ≤ 10s，回复非空中文（CPU 路径 / 3B 模型） | 模型已拉取并验证 |
| S6 | 打包产物完整性 | `sha256sum -c SHA256SUMS` 通过；GitHub 上传包解压后可执行 `aife setup` | checksum 100% 通过；GitHub 包 ≤ 100MB | 模型权重与 Ollama 二进制是否入包见 R8【待确认】 |
| S7 | 全量测试无 GPU 可跑 | `python -m pytest tests -q` | 全绿，且测试运行不需要 GPU/Ollama/网络 | 契约测试用 mock 探测输出 |

### 1.3 目标用户画像（3 类，按优先级排序）

| 画像 | 典型设备 | 核心诉求 | 硬约束 | AIE 对应承诺 |
|---|---|---|---|---|
| **P1 无 GPU 办公机用户**（最大基数，首要服务对象） | Windows/macOS 办公本，8–16GB RAM，Intel/Apple 集显，Ultra 系带 NPU | 不动脑子把 AI 用起来；数据不出本机；别把系统搞坏 | 不能装大体积软件、不能改系统全局环境、网络可能受限 | CPU 路径真实验证 + ≤15 分钟部署 + 卸载可回滚；NPU 探测到即提示，不做过度承诺 |
| **P2 有 NVIDIA 显卡的开发者/爱好者** | RTX 3060 以上，16GB+ RAM | 本地跑 7B–14B  instruct 模型；要速度；要 OpenAI 兼容 API 可脚本化/可集成 | 保持 Ollama 生态兼容；不接受黑盒 | GPU 剖面（`num_gpu=-1` 等参数）契约级交付 + 目标机验收清单 |
| **P3 国产 NPU / 信创设备用户** | Intel Core Ultra NPU、华为昇腾等 | 在国产算力上把 LLM 跑起来 | 驱动栈复杂、资料稀缺、环境碎片化 | 探测 + 剖面 + 显式「实验性/边界」标注；不承诺开箱即真跑（见 §4） |

### 1.4 核心场景（3 个）

- **场景 A｜冷启动一键部署**：用户拿到 AIE 压缩包 → 解压 → 单条命令 →（依赖检查 → 硬件探测 → Ollama 安装配置 → 模型拉取验证 → 服务启动）→ 浏览器打开即对话。触发时机：首次使用。期望：全程无需人工决策，失败时 doctor 能指出卡在哪一步、怎么修。
- **场景 B｜设备感知与加速选择**：安装阶段自动检测 GPU/NPU/CPU → 选择推理后端与加速路径（GPU 走 CUDA 剖面 / NPU 走实验剖面 / 都不支持走 CPU 回退）→ 对不支持加速的设备给出 CPU 回退方案 + 性能预期说明。期望：用户明确知道「我的机器在用什么算力、为什么」。
- **场景 C｜日常使用与自愈**：老用户日常 `aife serve` 启动 → Web/API 对话；环境漂移（Ollama 升级、端口被占、模型损坏）后 `aife doctor` 自检并给出可执行修复建议。期望：常见故障 5 分钟内自助定位。

### 1.5 现有替代方案与痛点

| 替代方案 | 痛点（AIE 要解决的） |
|---|---|
| Ollama 官网手动安装 | 需用户自行判断硬件该装什么版本、手动配环境变量/启动参数、手动拉模型、网络失败无引导；「最后一公里」完全裸奔 |
| LM Studio 等 GUI 工具 | GUI 重、难自动化/难服务器部署、硬件剖面知识不透明 |
| vLLM / llama.cpp 自建 | 门槛极高，不适合办公机用户 |
| 通用一键脚本（社区质量参差） | 无设备感知、无验证环节、无失败自愈、无诚实的能力边界声明 |

**真痛点结论**：不是「再做一个 Ollama 安装器」，而是把「探测 → 决策 → 安装 → 配置 → 验证 → 可观测」六个环节全部产品化，并用证据分级和 doctor 把不确定性变得可解释。

### 1.6 架构来源依据与 Octop 设计基因继承映射（对应用户原始需求第 6 条）

AIE 是 Octop 架构基因的继承 + 范围重构。下表每条基因均可回溯到 Octop 源码位置（Phase 2 架构师需复核）：

| Octop 设计基因（出处） | AIE 继承方式 | 对应需求/验收 |
|---|---|---|
| 硬件探测与厂商剖面分离 + E0–E3 证据分级（`octop/hardware.py`） | `aife/hardware.py` 同构；删除图像相关剖面；NPU 诚实边界（`caveats` 字段）保留 | US2.1/2.2/2.4；A1/A6/A7 |
| doctor 用真实 CLI 参数表求交验证（`octop/cli.py` + `comfy/process.py`） | doctor 核对 Ollama 版本、环境变量、端口连通性；参数拼错静默失败这类问题用版本兼容矩阵兜住 | US6.1；A2 |
| bootstrap 分阶段可跳过的 setup（`octop/bootstrap.py`：`--no-deps --no-comfy --no-ollama --no-model`） | `aife setup --no-ollama --no-model` 等分阶段重试，适配国内网络分步拉取 | US1.2；A3 |
| 双推理后端 + fallback 链 + last_errors（`octop/backends/`） | 本地 Ollama 为主后端，外部 API 为回退（Should）；回退原因可展示 | US5.4 |
| 单一 YAML 配置 + `${VAR}` 展开（`octop/config.py`） | `aife.yaml` 同构，端口/模型/后端均可配置 | 各模块 |
| 零构建前端，原生 ESM（`web/`） | 同构；移除节点画布/工作流 UI，只保留对话 | US5.2 |
| FastAPI 服务端口 8189（`octop/server/`） | `aife serve` 默认 8189（可配置），对外 OpenAI 兼容 | US5.1；A4 |
| 测试无需 GPU/Ollama 可跑（`tests/` 134 个） | 契约测试策略同构：mock `nvidia-smi`/NPU 探测输出断言剖面 | S7；A6/A11 |
| README「尚未在本环境验证的部分」诚实声明章节 | AIE README 必须有同构章节，逐条列出契约级未实测路径 | US7.x；A10 |
| ComfyUI 桥接（`octop/comfy/`）、图 IR、双模编译、文字出图 | **不继承**（范围重构砍掉） | §3.4 Won't have |

---

## 2. 用户故事地图

优先级说明：MoSCoW；RICE 为相对分值（Reach=覆盖用户比例 ×100，Impact=1–3，Confidence=0–1，Effort=人周），仅用于同 Epic 内排序参考。验收条件统一用 Given/When/Then。

| Epic | User Story | 优先级 | RICE | 依赖 | 验收条件（Given/When/Then） |
|---|---|---|---|---|---|
| E1 一键部署 | US1.1 作为新用户，解压后执行单条命令即完成全部安装配置，无需人工决策 | Must | 90 | US1.3 | Given 全新冷启动机（无 Ollama）且已解压 AIE 包，When 执行 `aife setup`，Then 退出码=0 且日志含 detect/install/configure/pull/verify/start 六个阶段时间戳 |
| E1 | US1.2 作为国内网络用户，setup 支持分阶段跳过与重试 | Must | 180 | US1.1 | Given 模型拉取阶段失败，When 执行 `aife setup --no-ollama --no-model`（或其他组合跳过），Then 已完成阶段不重复执行，断点可从日志指出 |
| E1 | US1.3 作为用户，setup 前先检查前置条件，不满足时明确拒绝并给出原因 | Must | 180 | — | Given 机器 RAM<8GB 或空闲磁盘<20GB 或 Python<3.10，When 执行 `aife setup`，Then 退出码非 0 且输出指明具体不满足项与建议值，不做无提示硬跑 |
| E1 | US1.4 作为用户，`aife serve` 启动服务并自检端口 | Must | 135 | US1.1 | Given 已完成 setup，When 执行 `aife serve`，Then 进程驻留、`curl -s 127.0.0.1:8189/v1/models` 返回 200 且含已安装模型 |
| E2 设备感知 | US2.1 作为用户，安装阶段自动检测 GPU（NVIDIA/AMD/Intel）/NPU/CPU 并输出机器可读结果 | Must | 135 | — | Given 任意支持矩阵内机器，When 执行 `aife detect --json`，Then 输出含每类设备的存在性、关键参数（如 CUDA 版本/显存）与选定加速路径 |
| E2 | US2.2 作为排障者，每条探测结论带证据等级（E0 实测/E1 工具输出/E2 推断/E3 猜测） | Must | 180 | US2.1 | Given 探测完成，When 查看 detect/doctor 输出，Then 每条设备结论均带 E0–E3 标记；无标记输出视为缺陷 |
| E2 | US2.3 作为无加速设备用户，机器不支持 GPU/NPU 时自动回退 CPU 并明确告知性能预期 | Must | 135 | US2.1 | Given 无 NVIDIA/AMD/Intel GPU 且无可用 NPU，When 执行 setup，Then 剖面为 CPU、输出含「当前为 CPU 推理，首 token 约 X 秒量级」类警告，且流程不中断 |
| E2 | US2.4 作为有独显用户，系统按硬件选择对应加速剖面（启动参数/环境变量） | Must | 54 | US2.1 | Given mock `nvidia-smi` 返回 RTX 4060，When 执行 detect，Then 剖面为 CUDA 且 `OLLAMA_*`/启动参数含 GPU 卸载配置（契约测试，见 A6） |
| E3 Ollama 安装与加速配置 | US3.1 作为用户，系统自动检测 Ollama 是否已装，未装则按平台自动安装（Win/macOS/Linux） | Must | 80 | US1.3 | Given 机器未装 Ollama，When 执行 `aife setup`，Then Ollama 可执行文件就位且 `ollama --version` 有输出；安装过程幂等（重复执行不重复下载） |
| E3 | US3.2 作为用户，系统按设备剖面设置 Ollama 环境变量与启动参数（GPU/NPU/CPU） | Must | 120 | US2.4 | Given 已选定剖面，When setup 完成，Then 生效配置写入 AIE 配置且 `aife doctor` 能回显每项环境变量及其来源 |
| E3 | US3.3 作为用户，安装后自动验证 Ollama 版本与连通性 | Must | 180 | US3.1 | Given Ollama 已安装，When setup 进入验证阶段，Then `ollama list` 或 API 探针成功；版本不在支持矩阵内时给出升级/降级建议而非静默继续 |
| E3 | US3.4 作为 GPU/NPU 用户，加速配置按契约交付（本机无 GPU，仅契约验证） | Must | 54 | US2.4 | Given mock 各厂商探测输出，When 执行剖面解析，Then 输出与剖面表逐项一致（GPU 层卸载、NPU 实验性 caveat 标注） |
| E4 模型管理 | US4.1 作为用户，setup 自动拉取默认模型（默认 `qwen2.5:3b`，【待确认】R4） | Must | 120 | US3.3 | Given Ollama 就绪，When setup 执行到模型阶段，Then `aife models list` 含默认模型且拉取日志含分块进度/断点续传行为 |
| E4 | US4.2 作为用户，可列出/删除本地模型 | Must | 180 | US4.1 | Given 已拉取模型，When 执行 `aife models list` / `aife models remove <name>`，Then 列表与实际一致，删除后探针确认不可用 |
| E4 | US4.3 作为用户，模型拉取后必须通过推理探针验证才算成功 | Must | 270 | US4.1 | Given 模型拉取完成，When 执行验证探针（发送固定 prompt），Then 返回非空且 HTTP 200；否则该阶段标记失败并在日志给出原因（损坏/不兼容/OOM） |
| E4 | US4.4 作为用户，系统按 RAM/显存推荐模型档位 | Should | 42 | US2.1 | Given 探测到 8GB RAM，When 用户请求推荐，Then 输出推荐档位（3B 级）与理由；LLM 不可用时规则阈值表给出同样结论 |
| E5 本地对话 | US5.1 作为开发者，服务提供 OpenAI 兼容 API（`/v1/chat/completions`、`/v1/models`） | Must | 108 | US1.4 | Given 服务已启动，When `curl 127.0.0.1:8189/v1/chat/completions -d '{"model":"qwen2.5:3b","messages":[{"role":"user","content":"你好"}]}'`，Then 返回 OpenAI 响应结构且 content 非空 |
| E5 | US5.2 作为普通用户，浏览器打开即用对话界面（零构建，无 npm 依赖） | Must | 80 | US1.4 | Given 服务已启动，When 访问 `http://127.0.0.1:8189`，Then 页面可发送消息并收到回复；前端资源为静态文件，`grep -r "node_modules" web/` 为空 |
| E5 | US5.3 作为用户，对话支持流式输出，中断后可继续 | Should | 56 | US5.1 | Given 正在生成，When 用户点击停止，Then 生成中止且已接收内容保留；流式通道中断时自动降级为非流式重试一次 |
| E5 | US5.4 作为用户，本地后端故障时可切换/回退外部 OpenAI 兼容 API | Should | 35 | US5.1 | Given 配置了 external_api 且本地 Ollama 不可用，When 发起对话，Then 请求走外部后端并在响应/日志中标注实际后端名（继承 Octop fallback.last_errors 设计） |
| E6 可观测与自愈 | US6.1 作为排障者，`aife doctor` 逐项体检并给出结论与修复建议 | Must | 135 | US2.1 | Given 任意状态机器，When 执行 `aife doctor`，Then 30 秒内完成硬件/后端/配置/端口/模型五类检查，每项输出 OK/FAIL/建议；对注入的常见故障（端口占用、模型损坏、版本过低）100% 正确识别 |
| E6 | US6.2 作为排障者，setup/serve 全过程有结构化 JSONL 日志（含阶段时间戳） | Must | 180 | US1.1 | Given 执行过 setup，When 查看日志目录（默认 `~/.aife/logs/`），Then 每次运行一个 JSONL 文件，含 start/end/duration_ms/level/stage 字段 |
| E6 | US6.3 作为排障者，doctor 的修复建议是可直接复制执行的命令 | Should | 49 | US6.1 | Given doctor 检出端口占用，When 查看该项输出，Then 附带形如 `aife serve --port 8190` 的可执行修复命令 |
| E6 | US6.4 作为运维者，服务提供健康探针端点 | Should | 96 | US1.4 | Given 服务运行中，When `curl 127.0.0.1:8189/healthz`，Then 返回 200 与后端连通状态 |
| E7 打包分发 | US7.1 作为发布者，一条命令产出三分平台压缩包与 checksum | Must | 135 | US1.1 | Given 代码库就绪，When 执行打包命令，Then 产出 `aife-<version>-win-x64.zip`、`-macos-arm64.zip`、`-linux-x64.zip` 与 `SHA256SUMS`，且校验通过 |
| E7 | US7.2 作为发布者，产出可直接上传 GitHub 的压缩包 | Must | 135 | US7.1 | Given 打包完成，When 检查 GitHub 包，Then 单文件 ≤100MB（超限方案见 R8【待确认】）、解压后可 `aife setup`、含 LICENSE 与 README |
| E7 | US7.3 作为用户，可一键更新 AIE 自身与模型 | Could | 30 | US7.1 | Given 已安装旧版本，When 执行 `aife update`，Then 提示版本差异并经确认后升级，失败可回滚 |
| E7 | US7.4 作为离线用户，可导入本地模型文件而非在线拉取 | Could | 10 | US4.1 | Given 用户持有本地 gguf/blob 文件，When 执行 `aife models import <path>`，Then 模型注册可用且通过 US4.3 探针 |

---

## 3. MVP 范围（MoSCoW）

### 3.1 本期必做（Must，共 8 项）

| # | 范围项 | 覆盖用户故事 | 完成定义 |
|---|---|---|---|
| M-1 | CLI 三件套：`aife setup / doctor / serve`（+ `detect / models / chat` 子命令） | US1.1–1.4、US6.1 | S1–S4 达标 |
| M-2 | 硬件探测：NVIDIA/AMD/Intel GPU、NPU 探测、CPU 兜底，E0–E3 证据分级 | US2.1–2.3 | S3 达标；A1/A7 通过 |
| M-3 | Ollama 自动安装（Win/macOS/Linux x64+arm64）+ 按剖面配置环境变量与启动参数 + 版本兼容矩阵 | US3.1–3.3 | A3 通过 |
| M-4 | 模型拉取 + 推理探针验证 + 列表/删除 | US4.1–4.3 | A8 通过 |
| M-5 | OpenAI 兼容 API + 零构建 Web 对话界面 | US5.1–5.2 | A4/A5 通过 |
| M-6 | JSONL 结构化日志 + doctor 体检（五类检查、≥95% 常见失败覆盖、可执行修复建议） | US6.1–6.2 | A2/A12 通过 |
| M-7 | 三分平台压缩包 + SHA256SUMS + GitHub 上传包 | US7.1–7.2 | A9/A10 通过 |
| M-8 | README + 部署文档 + 「未实测路径」诚实声明 | （贯穿） | 声明与 §1 表头一致 |

**支持矩阵（S2 口径内的范围）**：Windows 10/11 x64、macOS 13+（arm64/x64）、Linux x64（Ubuntu 22.04+/Debian 12+）；Python 3.10–3.12；Ollama 官方支持版本区间（版本兼容矩阵在 M-3 定义）。矩阵外平台：doctor 明确报「不支持」，不允许带病运行。

### 3.2 Should have（重要但可降级，共 4 项）
- S-1 外部 API 后端回退（OpenAI 兼容），本地故障时可切换（US5.4）
- S-2 模型档位推荐：规则阈值表 + LLM 辅助，LLM 不可用不影响推荐（US4.4）
- S-3 `aife update` 一键更新自身与模型（US7.3）
- S-4 健康探针 `/healthz` + doctor 修复建议命令化（US6.3/6.4）

### 3.3 Could have（资源富余则做，共 4 项）
- C-1 对话历史本地持久化（SQLite，单用户）
- C-2 模型量化档位选择向导（q4/q5/q8）
- C-3 离线模型导入（US7.4）
- C-4 Web UI 多会话管理

### 3.4 本期不做（Won't have）与原因

| 砍掉项 | 原因（砍断的代价已评估） |
|---|---|
| **ComfyUI 图像工作流整体**（节点画布、文字出图、图 IR、双模编译、`comfy/` 桥接、自定义节点） | 主理人明确范围重构：AIE 聚焦 LLM 本地化部署。代价：图像用户不服务；换来体积与依赖大幅缩小、部署路径变短 |
| 训练 / 微调 / LoRA 训练 | 与「一键部署」目标正交，且硬件门槛高 |
| 多租户鉴权 / 计费 / 商业化 | 单用户本地产品；引入后配置复杂度爆炸 |
| 分布式多机推理 / 集群 | 无对应场景 |
| 移动端 App | Web UI 已覆盖移动浏览器 |
| MSI/EXE 安装包（含代码签名/公证） | 用户明确要求压缩包呈现；签名与公证涉及证书采购与审核周期，列为后续候选 |
| 前端构建链（npm/vite/框架） | 继承 Octop 零构建前端基因，去掉画布后原生 ESM 足够 |

---

## 4. 非目标与边界声明（AIE 不承诺什么）

1. **不承诺 GPU/NPU 实测加速倍数**：本机无 GPU，加速剖面基于 Ollama 官方文档与版本兼容矩阵推导，只做契约级验证；「快多少倍」必须由目标机用户按 A 类验收清单实测后自行得出。
2. **不承诺国内网络模型/Ollama 拉取 100% 成功**：网络不可控；AIE 提供分阶段重试、镜像/代理配置点与失败诊断，但不保证结果。
3. **不承诺 ComfyUI 相关图像能力**：范围重构后已整体移除，任何文档不得暗示图像生成。
4. **不承诺 NPU 全场景可用**：NPU（尤其 Intel NPU）LLM 侧支持随 Ollama 版本演进，标注「实验性」；NPU 图像侧在 Octop 即无支持，AIE 无此方向。
5. **不替代 Ollama 官方客户端**：AIE 是部署与管理层，兼容 Ollama 生态与模型格式；Ollama 自身能力边界即 AIE 边界。
6. **模型权重与第三方二进制不分发给 GitHub 包**（默认方案，见 R8）：涉及许可与仓库体积。
7. **不做安全承诺越界**：本地服务默认绑定 127.0.0.1；如需局域网访问，文档明确提示风险并给出绑定配置，但不默认开启、不提供鉴权重型方案（见 Won't have）。

---

## 5. 人机边界（AI 环节划分）

| 环节 | 执行方 | 理由 | 兜底策略 |
|---|---|---|---|
| 硬件探测（nvidia-smi / WMI / rocm-smi / sysfs / 环境变量） | 确定性代码 | 事实判断必须确定且可复现 | 探测失败 → CPU 剖面 + E2/E3 证据标注 + 显式警告 |
| Ollama 下载/安装/环境变量/启动参数 | 确定性代码 | 可重复、可回滚、可测试 | 失败 → doctor 定位 + 分阶段重试 |
| 模型拉取与完整性验证 | 确定性代码 | 正确性判断不能交给概率模型 | 探针失败 → 标记损坏/不兼容/OOM 并给重拉指引 |
| 打包与 checksum | 确定性代码 | 完整性要求 | 校验失败即发布失败 |
| 模型档位推荐（按 RAM/VRAM/用途） | 智能体（LLM）+ 规则表 | 需综合多因素推理，有生成空间 | LLM 不可用 → 规则阈值表给出同构结论 |
| 对话生成 | 智能体（本地 Ollama） | 核心生成任务 | 本地故障 → 外部 API 回退（Should）；再失败 → 明确报错不假装成功 |
| doctor 修复建议的自然语言解释 | 智能体生成 + 确定性模板 | 解释性文本适合生成 | 模板化建议保证可用（建议本体是确定性命令） |
| Web 对话流式展示 | 确定性代码 + 智能体输出 | 传输层必须确定 | 流式中断 → 非流式重试一次 → 失败提示（继承 Octop 轮询兜底基因） |

原则（继承 Octop）：**能用规则解决的不上模型；LLM 返回垃圾时静默回退规则结果；用户在配置里显式写死的参数，LLM 无权覆盖。**

---

## 6. 指标与埋点

| 指标 | 定义与口径 | 目标值 | 数据来源 |
|---|---|---|---|
| 北极星：部署一次跑通率 | setup 退出码=0 且 serve 后 `/v1/models` 200 的运行次数 / 总运行次数 | ≥90%（支持矩阵内） | setup JSONL 日志聚合 |
| 部署总时长 | setup 起点 → 首次推理成功，P50/P95 | P50 ≤15min（CPU/3B） | 同左（阶段时间戳差） |
| 阶段耗时分解 | detect / install / configure / pull / verify / start 各阶段 P50/P95 | 用于定位瓶颈，无绝对目标 | 同左 |
| 首 token 延迟 | 探针请求发出到收到首个 token | ≤10s（CPU/3B） | `aife chat --json` 或 API 计时 |
| 设备检测准确率 | detect 输出 vs 实际硬件（抽检） | 100% | 人工抽检 + doctor 回显 |
| doctor 覆盖率 | 常见失败模式清单中有诊断项的比例 | ≥95% | 测试注入故障对账 |
| CPU 回退告知率 | 触发 CPU 回退的运行中，输出含警告的比例 | 100% | 日志字段 `fallback_warned=true` |
| 匿名统计（可选） | 部署成功率/阶段耗时，**默认关闭，opt-in** | 开启率不作考核 | 本地聚合 + 用户显式上传 |

---

## 7. 验收标准总表（每条对应可执行命令或可观测输出）

| # | 验收项 | 可执行命令 / 可观测输出 | 通过标准 | 验证等级 |
|---|---|---|---|---|
| A1 | 设备检测输出 | `aife detect --json` | 输出本机 CPU 20 核/95.5GB RAM、无 CUDA 设备、选定 CPU 剖面，每项带证据等级 | **真实**（本机） |
| A2 | doctor 体检 | `time aife doctor` | ≤30s；五类检查逐项 OK/FAIL/建议；无 Ollama 的裸机不崩溃 | **真实** |
| A3 | 一键部署冷启动 | 全新环境执行 `aife setup` | 退出码 0；日志含六阶段时间戳；幂等（二次执行不重复下载） | **真实**（CPU 路径） |
| A4 | 服务与 API 契约 | `aife serve` 后 `curl -s 127.0.0.1:8189/v1/models` | HTTP 200 且含默认模型名 | **真实** |
| A5 | 模型推理测试 | `aife chat "你好，请用一句话介绍你自己"` | 首 token ≤10s；回复非空中文 | **真实** |
| A6 | GPU 剖面契约 | mock `nvidia-smi`（RTX 4060）输入跑 detect 单测 | 剖面=CUDA，启动参数含 GPU 卸载配置，断言逐项一致 | **契约**（mock） |
| A7 | CPU 回退契约 | 本机（无 GPU）执行 setup | 剖面=CPU；输出含 CPU 推理性能预期警告；流程不中断 | **真实** |
| A8 | 模型拉取与验证 | `aife models pull qwen2.5:3b` → `aife models list` → 探针 | 列表可见 + 探针 200 非空；故意损坏模型后 doctor 能识别 | **真实** |
| A9 | 分平台打包产物 | 执行打包命令 → `sha256sum -c SHA256SUMS` | 三分平台 zip + checksum 全部通过 | **真实**（打包）；各平台解压 Smoke（win 真实，mac/linux 契约） |
| A10 | GitHub 上传包 | 检查包大小/内容 → 解压 → `aife setup` | ≤100MB；含 LICENSE/README；解压后可部署 | **真实**（win）；方案见 R8 |
| A11 | 全量测试无 GPU 可跑 | `python -m pytest tests -q` | 全绿；运行环境不需要 GPU/Ollama/外网 | **真实** |
| A12 | 启动日志结构 | 检查 `~/.aife/logs/setup-*.jsonl` | 含 start/end/duration_ms/level/stage 字段 | **真实** |

> 诚实边界：A6 及 NPU/AMD/Apple 相关验收**仅契约级**；「GPU 实测加速收益」列入目标机验收清单，由用户在真实硬件上执行，本交付不提供实测数字。

---

## 8. 里程碑建议（M1–M4）

人力假设：**1 名全栈工程师全职 + 本专家团评审计**（每个里程碑结束评审半天，输出放行/返工结论）。

| 里程碑 | 周期 | 内容 | 交付物与出口条件 | 依赖 |
|---|---|---|---|---|
| **M1 骨架与契约** | 1 周 | 仓库与目录结构（`aife/` 包、`web/`、`config/`、`tests/`、`scripts/`）；CLI 入口；`hardware.py` 探测 + 剖面分离 + 证据分级；契约测试框架（mock 探测输出） | `aife detect`/`aife doctor` v0 可用；`pytest` 全绿无 GPU；目录结构评审通过 | 无 |
| **M2 Ollama 安装与模型** | 1.5 周 | bootstrap（Ollama 自动安装 + 环境变量 + 启动参数 + 版本兼容矩阵）；`models pull/list/remove/verify`；**CPU 路径端到端真实验证（本机）**；GPU/NPU 契约测试 | A1/A2/A3/A7/A8/A11 通过；setup JSONL 日志落地 | M1 |
| **M3 服务与前端** | 1 周 | FastAPI + OpenAI 兼容 API；零构建 Web 对话；流式 + 中断降级；双后端回退（S-1，若延期则降级为单后端 + 明确 TODO）；健康探针 | A4/A5 通过；US5.1–5.3 验收通过 | M2 |
| **M4 打包分发与文档** | 1 周 | 三分平台打包脚本 + checksum；GitHub 上传包（R8 方案落地）；README/部署文档/诚实声明；全量验收清单跑通 | A9/A10/A12 通过；§7 表中「真实」项全绿；专家团终审放行 | M3 |

关键路径：M1→M2→M3→M4 串行；M2 内「CPU 真实验证」是关键路径上的关键节点，若国内网络拉模型受阻（R1），优先落地镜像方案再继续，不允许用「跳过验证」充数。

---

## 9. 风险与假设登记

| # | 类型 | 内容 | 影响 | 对策 / 责任 |
|---|---|---|---|---|
| R1 | 风险【待确认】 | 国内网络 Ollama 与模型拉取的镜像/代理方案未定（hf-mirror / modelscope / 自建代理？） | 直接威胁 S1/S2 | M2 前由主理人拍板；setup 预留 `--mirror` 配置点 |
| R2 | 风险【待确认】 | 分平台打包中 Ollama 二进制是否入包：方案 A 入包（即开即用但可能超 100MB）；方案 B 仅脚本 + 首装下载（小但依赖网络） | 决定 GitHub 包形态与 S1 口径 | 需主理人业务判断；本需求默认方案 B（权重与二进制不入包） |
| R3 | 风险【待确认】 | NPU 优先级未定：Intel Core Ultra NPU / 华为昇腾 CANN / 其他 | 决定 E3 加速配置工作量 | 本期 NPU 仅探测 + 实验性标注，不做深度适配 |
| R4 | 假设【待确认】 | 默认模型档位设为 `qwen2.5:3b`（中文效果/体积/许可综合权衡） | 影响 A5/A8 与 S1 | 需主理人确认；配置项可改 |
| R5 | 假设 | 用户机器 ≥8GB RAM、≥20GB 空闲磁盘、Python 3.10+ | 低于此机器 US1.3 明确拒绝 | 前置检查硬编码，不做「尽力而为」 |
| R6 | 风险 | Ollama 版本升级导致 CLI/API 行为漂移 | 安装/配置步骤失效 | 版本兼容矩阵 + doctor 版本核对（继承 Octop 基因） |
| R7 | 风险 | 本机无 GPU：GPU/NPU 路径契约验证 ≠ 真实可用 | 用户期望管理 | README 诚实声明 + 目标机验收清单（随包分发） |
| R8 | 风险 | 压缩包在 GitHub 的单文件 100MB 限制与仓库体积治理 | 分发形态 | 同 R2；checksum + Release 资产而非仓库内大文件 |
| R9 | 假设 | 前端保持零构建（原生 ESM），不引入 npm 链 | 开发效率与可维护性 | 若 M3 发现交互复杂度超预期，升级为架构决策项提交主理人，不擅自加构建链 |
| R10 | 假设 | macOS 不做代码签名/公证（压缩包形态天然规避） | 用户首次打开可能遇 Gatekeeper 提示 | README 写明 `xattr -d com.apple.quarantine` 处置 |

---

## 10. 主理人裁决记录（Phase 2 开工前，高屋建）

| # | 待确认项 | 裁决 | 理由 |
|---|---|---|---|
| D1（对应 R1） | 国内网络镜像方案 | **采纳「多镜像回退 + 显式配置点」**：`ollama` 官方安装脚本与模型拉取均支持 `OLLAMA_API_BASE`/代理环境变量；setup 提供 `--mirror` 配置项与 `aife.yaml` 的 `network.mirror` 字段，默认官方源，失败时按内置镜像清单回退并明确告知用户走了哪条路 | 不静默改流量走向；与 Octop「不静默下载、失败给指引」基因一致 |
| D2（对应 R2） | 二进制/权重是否入包 | **方案 B：压缩包只含 AIE 源码与脚本，不含 Ollama 二进制与模型权重**；`aife setup` 首装时按平台自动下载安装 Ollama。GitHub 包 ≤100MB 由此天然满足 | 体积、许可、平台矩阵（Win/macOS/Linux × x64/arm64 = 6 个二进制）三者都指向「不入包」；用户明确要 GitHub 可上传包 |
| D3（对应 R3） | NPU 优先级 | **本期 NPU = 探测 + 实验性剖面 + 显式 caveats，不做深度适配**；Intel NPU 优先（本机即 Intel 平台），昇腾等仅在探测层留扩展位 | 与 §4 边界声明一致；Ollama 官方对 NPU 的支持本身在演进中 |
| D4（对应 R4） | 默认模型 | **默认 `qwen2.5:3b`**（可在 `aife.yaml` 的 `ollama.model` 修改）；`aife models recommend` 按 RAM/VRAM 给档位建议 | 中文效果/体积/许可综合最优；3B 在 CPU 上首 token 可达 S5 目标 |
| D5 | 端口与命令名 | 服务默认端口 **8189**（继承 Octop）；命令名统一 `aife`；包名 `aife` | 与 Octop 基因一致，降低迁移认知 |
| D6（对应 S-1） | 外部 API 回退是否降级 | **不降级，按 Should 实现**：后端抽象 + 注册表 + fallback 链是 Octop 已验证基因，边际成本低；但 M3 若延期，允许先上单后端 + TODO 注释，接口预留 | 接口先行，实现可降级 |

以上 6 项裁决完，Phase 2 各专项可直接引用本文档条目编号（US-x / A-x / S-x / R-x / D-x）作为设计输入。

—— 许可研（场景产品策略师），Phase 1 需求侧交付完毕。
