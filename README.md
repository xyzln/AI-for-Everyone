# AI For Everyone (AIE)

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)
![Backends](https://img.shields.io/badge/Backends-Ollama%20%7C%20llama.cpp%20%7C%20vLLM-blueviolet.svg)
![Desktop](https://img.shields.io/badge/Desktop-native%20window%20%2B%20tray-2b6cb0.svg)

> 一条命令，把本地大模型跑起来。AIE 是基于 [Octop](https://github.com/) 参考架构重新实现的 **本地 LLM 一键部署工具**：硬件探测 → 依赖检查 → Ollama 安装与加速配置 → 模型拉取与验证 → 本地服务启动 → 浏览器即用。

**核心承诺**

- **一键部署**：`aife setup` 串起全部阶段，失败不静默退出，给出人工修复指引。
- **设备感知**：安装时自动探测 GPU / NPU / CPU，选择推理后端与加速方案，CPU 永远兜底。
- **加速配置**：按硬件剖面注入 Ollama 加速环境变量；`num_gpu` 以**请求级 options** 传入（已勘误：`OLLAMA_NUM_GPU` 不是环境变量）。
- **CPU 一等公民**：无显卡的机器（如 Intel Core Ultra 7 265K）也能完整跑通；默认推荐 3B 级小模型。

---

## 1. 快速开始

**最省事（Windows 用户）**：下载 `dist/aife-<ver>-win-portable.zip`，解压后双击 `launch-AIE.bat` —— 直接打开**原生桌面窗口**（无需安装 Python，也不跳浏览器）；窗口不可用时自动回退浏览器。

**开发者 / 源码方式**：

```bash
# 1) 安装 AIE（以 Windows 为例，Linux/macOS 见下方安装脚本）
python -m venv .venv && .venv\Scripts\activate
pip install -e .

# 2) 一条命令完成部署（探测 → 装 Ollama → 拉模型 → 起服务）
aife setup

# 3) 浏览器打开 http://127.0.0.1:8189 即可对话
```

部署完成后服务已在运行；若只想部署不自动起服务，用 `aife setup --no-serve`，之后随时 `aife serve`。

---

## 2. 安装（三平台）

仓库根提供安装脚本，自动检测 Python（要求 ≥3.10）、建 venv、装依赖、注册 `aife` 命令：

| 平台 | 命令 |
|------|------|
| Windows | `powershell -ExecutionPolicy Bypass -File scripts/install-windows.ps1` |
| Linux | `bash scripts/install-linux.sh` |
| macOS | `bash scripts/install-macos.sh` |

依赖严格控制在 **6 个以内**：`fastapi`、`uvicorn`、`httpx`、`pydantic`、`PyYAML`、`websockets`（`torch` 仅作探测惰性导入，非硬依赖）。

---

## 3. 一键部署详解

`aife setup` 按阶段推进，每阶段可单独跳过以便复跑：

```
deps    依赖检查
  ↓
hardware  硬件探测（nvidia-smi → rocm-smi → Intel NPU PnP → MPS → CPU 兜底）
  ↓
ollama   安装并启动 Ollama（注入加速环境变量；缺失则按平台指引分阶段重试）
  ↓
model    按硬件剖面推荐并拉取默认模型（如 qwen2.5:3b）
  ↓
verify   深度健康检查（含默认模型存在性校验）
  ↓
start    启动本地服务（可选）
```

常用参数：`--skip-deps` / `--skip-ollama` / `--skip-model`（复跑阶段）、`--model NAME`（指定模型）、`--dry-run`（只演不跑）、`--no-serve`（部署后不起服务）。进度通过 WebSocket 实时推送到 Web UI 向导页。

---

## 4. 设备感知与加速

`aife detect` 打印当前硬件剖面。剖面优先级：**CUDA > ROCm > Intel XPU > Apple MPS > AMD Vulkan > Intel NPU > CPU**。

- 每个 `VendorProfile` 固化一份 **Ollama 加速环境变量白名单**（`OLLAMA_HOST` / `OLLAMA_KEEP_ALIVE` / `OLLAMA_MAX_LOADED_MODELS` 等），由 `OllamaManager` 注入子进程。
- `num_gpu`（GPU 层卸载数）**只**经 `/api/chat` 的 `options.num_gpu` 传入（0=CPU，-1=自动），`backends/ollama.py` 在每次推理请求时注入 —— 改配置下一请求即生效，不重启 Ollama。
- 模型分档（D8）：RAM < 8GB → `qwen2.5:1.5b`；8–16GB → `qwen2.5:3b`；16–32GB → `qwen2.5:7b`；> 32GB 或 GPU VRAM ≥ 12GB → `qwen2.5:14b`。本机 95.5 GiB 内存 → 推荐 `14b` 档。

### 推理后端与 OpenAI 兼容

AIE 通过统一的 `LLMBackend` 抽象支持多种推理后端，由 `backends.active` 选择、`backends.fallback` 降级：

| 后端 | 引擎 | 模式 | 适用 |
|------|------|------|------|
| `ollama` | Ollama 子进程 | AIE 托管拉起 | 默认；跨 CPU/GPU/Metal/Vulkan，模型管理一体 |
| `llamacpp` | `llama-server` | adopted（接已在跑）/ managed（AIE 拉起） | CPU/GPU/Vulkan/Metal；GGUF 模型 |
| `vllm` | `vllm serve` | adopted / managed | GPU（CUDA/ROCm）高吞吐 |
| `openai_compat` | 远端 OpenAI 兼容 API | 连接 | 混合/远程场景 |

`llamacpp` 与 `vllm` 本身暴露 OpenAI 兼容 HTTP（`/v1/chat/completions`、`/v1/models`、`/health`），AIE 用一个「受管 OpenAI 服务器」基类复用该协议，无需重复实现推理客户端。

**AIE 自身也对外暴露 OpenAI 兼容接口 `/v1`**，任何 OpenAI SDK 可零改造接入（`base_url` 指向 `http://127.0.0.1:8189/v1`）：

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8189/v1", api_key="x")
client.chat.completions.create(model="qwen2.5:3b",
    messages=[{"role": "user", "content": "你好"}], stream=True)
```

配置示例（llamacpp adopted 模式）：
```yaml
llamacpp:
  enabled: true
  base_url: http://127.0.0.1:8081   # 接已在跑的 llama-server；填 binary 则由 AIE 托管拉起
backends:
  active: llamacpp
```

---

## 5. 命令行

| 子命令 | 用途 |
|--------|------|
| `aife setup` | 一键部署（见 §3） |
| `aife doctor` | 环境体检，逐项结论 + 修复建议；`--json` 可解析 |
| `aife detect` | 硬件探测与剖面解析；`--json` 输出 |
| `aife serve` | 启动 Web 服务（`--host` / `--port` / `--no-browser` / `--window` 开原生窗口） |
| `aife desktop` | 打开**原生桌面窗口**（pywebview 包现有 UI；失败自动回退浏览器） |
| `aife chat` | 命令行对话（`--model` / `-m` / `--stream`） |
| `aife models` | 模型管理（`list` / `pull NAME` / `rm NAME` / `show NAME`） |
| `aife backend` | 后端管理（`list` / `use NAME`） |
| `aife bench` | 本地压测（`--model` / `--duration` / `--concurrency`） |
| `aife openapi` | 导出 OpenAPI JSON |

---

## 6. Web UI

零构建原生 ESM 单页，FastAPI 静态托管，无 npm / 无打包器 / 无框架。四个视图：

- **部署向导**：触发 `setup`、实时展示进度与修复指引。
- **聊天**：SSE 流式渲染、模型切换、温度等参数。
- **模型**：已装列表 / 推荐目录 / 拉取 / 删除，进度条实时更新。
- **状态**：系统信息、深度健康检查、设备卡片、后端状态、重启 Ollama。

通信走 `fetch` + 原生 `WebSocket` + `SSE`；统一错误体在前端解析为中文提示。

### 桌面窗口
同一套 UI 也可包进**原生桌面窗口**：`aife desktop`（或便携包双击 `launch-AIE.bat`）用 pywebview + 系统自带 WebView2 渲染，带应用图标、顶栏品牌图与首屏启动动画，**不跳浏览器**。WebView2 不可用时自动回退浏览器，绝不更差。

- **系统托盘 / 最小化到托盘**：默认启用（`pystray` 可选依赖）；最小化即隐藏到托盘，托盘菜单可 显示/隐藏、在浏览器打开、退出。`aife desktop --no-tray` 或配置 `desktop.tray: false` 关闭；无 pystray 时自动跳过、窗口照常。
- **快捷方式 / 开机自启**（Windows 便携包内）：`portable-创建桌面快捷方式.bat`、`portable-安装开机自启.bat`、`portable-卸载开机自启.bat`。
- **窗口版打包**：Windows 用 `packaging/aife_desktop.spec`（无控制台 + 图标 exe）；macOS/Linux 因 PyInstaller 不支持跨平台，需在目标系统运行 `scripts/build-desktop-macos.sh`（产出 `AIE.app`）或 `scripts/build-desktop-linux.sh`。源码方式需 `pip install -e ".[desktop]"`。
- **未就绪引导**：尚无可用推理后端（如未装 Ollama）时，窗口顶部显示「服务尚未就绪 → 去一键部署」引导条（就绪后自动消失），不会满屏报“不可达”。

---

## 7. 配置

单一 YAML 真相源，默认位于 `~/.aife/config.yaml`（首次运行从仓库模板 `config/aife.yaml` 复制），支持 `${VAR}` 环境变量展开与 pydantic 校验。`PATCH /api/config` 可热切换后端/剖面（涉及 Ollama 启动参数的变更会重启子进程），不重启 `aife-server`。

```yaml
config_version: 1
hardware:
  device: auto            # auto 由 resolve_profile 求解
ollama:
  host: 127.0.0.1
  port: 11434
  autostart: true
  keep_alive: 5m
  max_loaded_models: 1
models:
  default: null           # null = 按硬件剖面推荐
backends:
  active: ollama
server:
  host: 127.0.0.1         # 默认仅本地；远程访问见文档风险说明
  port: 8189
openai_compat:            # 可选远程/混合后端
  base_url: ${AIE_OPENAI_BASE_URL:-}
  api_key: ${AIE_OPENAI_API_KEY:-}   # 密钥只引用环境变量，不落明文
```

---

## 8. API 概览

REST 前缀 `/api`，所有错误响应统一为 `{"error":{"code","message","details","trace_id"}}`；事件经 `WS /ws/events` 广播。

| 端点 | 说明 |
|------|------|
| `GET /api/health`、`GET /api/health/deep` | 探活 / 深度健康（恒 200，含 checks） |
| `GET /api/system`、`GET /api/hardware` | 系统信息 / 硬件剖面与设备 |
| `GET /api/config`、`PATCH /api/config` | 配置视图 / 热切换 |
| `GET /api/models`、`GET /api/models/available` | 已装模型 / 推荐目录 |
| `POST /api/models/pull`、`DELETE /api/models/{name}` | 拉取（202 + WS 进度）/ 删除 |
| `POST /api/chat`、`POST /api/chat/stream` | 非流式 / SSE 流式对话 |
| `GET /api/backends`、`POST /api/backends/select` | 后端注册表 / 切换 |
| `POST /api/setup/run`、`GET /api/setup/status` | 触发部署 / 状态 |
| `POST /api/ollama/restart` | 重启 Ollama 子进程 |

**OpenAI 兼容面 `/v1`**（错误用 OpenAI 信封 `{"error":{"message","type","code","param"}}`，与 `/api` 分离）：

| 端点 | 说明 |
|------|------|
| `GET /v1/models` | OpenAI 风格模型列表 |
| `POST /v1/chat/completions` | 对话；`stream:true` 返 SSE `chat.completion.chunk` + `[DONE]`，否则返 `chat.completion` |

---

## 9. 架构与来源

AIE 直接继承并改造自 **Octop** 参考项目（`@"C:/Users/DELL/WorkBuddy/rea/octop"`），落地映射见 `docs/design/02-architecture.md` §9：

| Octop 模块 | AIE 模块 | 改造要点 |
|-----------|----------|----------|
| `hardware.py` | `aife/hardware.py` | 删 ComfyUI 参数；增 `ollama_accel` 环境变量白名单与 `min_ram_gb` 分档 |
| `backends/` | `aife/backends/` | 健康检查强制「缺模型判不健康」（Octop M14 教训）；返回全 pydantic |
| `bootstrap.py` | `aife/bootstrap.py` | 阶段改为 deps→ollama→model→verify；可跳过、失败指引 |
| `config.py` | `aife/config.py` | 增 `config_version` 与 `reload()` 热切换 |
| `cli.py` | `aife/cli.py` | 砍 plan/run（并入 `--dry-run`/`-m`）；增 models/chat |
| `runtime.py` | `aife/runtime.py` | ComfyUI 桥接 → OllamaManager，单例组装无循环 import |
| `server/app.py` | `aife/server/` | 拆 routes/；统一错误契约；静态托管 ESM |
| — | `aife/ollama/{manager,protocol}.py` | 新增：安装检测/守护/环境变量注入；version/tags/ps/chat/pull/show |
| — | `aife/models/{catalog,manager}.py` | 新增：能力→推荐档位；拉取任务态/进度/防重 |
| — | `aife/web/`（ESM） | 新增：向导/聊天/模型/状态四视图 |
| — | `scripts/` + `.github/workflows/ci.yml` | 新增：三平台安装/打包；无 GPU CI matrix |

设计裁决（D1–D30）、模型分档（D8）、版本矩阵（D11，最低 Ollama v0.5.0）等见 `docs/design/00-decisions.md`。

---

## 10. 开发测试

全部测试可**在无 GPU、无 Ollama、无网络**环境下运行（Ollama HTTP 由 `httpx.MockTransport` 取代，manager 被 patch 为健康）：

```bash
pip install -e ".[dev]"   # 含 pytest
pytest -q
```

覆盖：`config`（`${VAR}` 展开/校验/热切换）、`hardware`（CPU 兜底/降级链）、`ollama protocol`（NDJSON 解析/错误映射）、`backend contract`（num_gpu 注入/缺模型不健康）、`server api`（全路由 + 统一错误体）、`errors`（错误码快照）。

---

## 11. 打包分发

```bash
# 1) 构建 Windows 免安装独立包（PyInstaller，内置 Python 运行时，无需装 Python）
pyinstaller packaging/aife.spec --noconfirm --distpath dist/pyinstaller --workpath build/pyinstaller

# 2) 生成全部分发包 + SHA256SUMS 到 dist/
python scripts/package.py
```

产物（`dist/`）：

- **`aife-<ver>-win-portable.zip`** —— Windows **免安装独立包**（推荐给普通用户）：内含 `aife.exe`（内置 Python 与全部依赖）、`launch-AIE.bat`（双击即启动服务并打开浏览器）、`README.txt`。解压即用，**无需安装 Python**。
- `aife-<ver>-win-x64.zip` / `aife-<ver>-macos-arm64.zip` / `aife-<ver>-linux-x64.zip`（≤ 30MB 源码包，供开发者用安装脚本搭建）
- `aife-<ver>-source.zip`（GitHub 上传包，≤ 100MB）
- `SHA256SUMS`

**跨平台隔离**：每个平台源码包只含**本平台**的安装脚本（Windows 包只含 `install-windows.ps1`，macOS 只含 `install-macos.sh`，Linux 只含 `install-linux.sh`），不掺杂其它系统的安装/包管理器协议；`source.zip` 含全部平台脚本。分发包不含 Ollama 二进制与模型权重，首次运行按平台下载（D2）。

---

## 12. 许可

MIT —— 见 `LICENSE`。
