# AIE 主理人裁决记录（ consolidated decision log ）

> 主理人：高屋建（首席交付架构师）。本文件汇总全部裁决；D1–D6 全文见 `01-requirements.md` §10，D7–D16 全文见 `02-architecture.md` §11，此处仅列目录与新增裁决全文，供追溯。

## 裁决目录

| ID | 事项 | 出处 | 一句话结论 |
|---|---|---|---|
| D1 | 国内网络镜像方案 | 需求 R1 | 多镜像回退 + 显式配置点，不静默改流量 |
| D2 | 二进制/权重入包 | 需求 R2 | 方案 B：压缩包只含源码与脚本，首装下载 Ollama |
| D3 | NPU 优先级 | 需求 R3 | 本期仅探测 + 实验性标注，Intel NPU 优先 |
| D4 | 默认模型 | 需求 R4 | `qwen2.5:3b`，可配置 |
| D5 | 端口与命令名 | 需求 §10 | 端口 8189；包名/命令名 `aife` |
| D6 | 外部 API 回退 | 需求 S-1 | 不降级，接口预留 |
| D7 | 包名/命令名统一 | 架构 §10.3-1 | `aife`（架构正文 "aie" 字样同指） |
| D8 | 模型分档表 | 架构 §10.3-2 | 1.5b/3b/7b/14b 按 RAM 与 VRAM 分档（详见 04-data-model §2.1.4） |
| D9 | Ollama 安装优先级 | 架构 §10.3-3 | 包管理器优先 → 官方脚本 → 手动指引 |
| D10 | 远程访问 | 架构 §10.3-4 | MVP 默认 127.0.0.1，不设 token 鉴权 |
| D11 | Ollama 版本矩阵 | 架构 §10.3-5 | 最低 v0.5.0，更低明确报不支持 |
| D12 | Apple Silicon | 架构 §10.3-6 | 统一内存按总 RAM 分档，Metal 不设 num_gpu |
| D13 | 配置目录 | 架构 §10.3-7 | 运行时状态在 `~/.aife/`，仓库模板 `config/aife.yaml` |
| D14 | UI 语言主题 | 架构 §10.3-8 | v1 仅简体中文、浅色 |
| D15 | bench 指标 | 架构 §10.3-9 | TTFT ≤10s（CPU/3B）体验阈值，tok/s 只报告 |
| D16 | 遥测 | 架构 §10.3-10 | 不实现，无埋点 |
| D17 | OLLAMA_API_BASE 无法证实 | 安智体 R-11 | **不注入**该变量；国内网络走 `HTTPS_PROXY` + 安装包本地化 + 模型 mirror 配置点 |
| D18 | D8 与 US1.3（<8GB 拒绝）张力 | 安智体 R-12 | catalog 保留 1.5b 档（完整性）；setup 默认拒绝 <8GB 并给 `--force` 逃生阀 |
| D19 | 流式重试规则冲突（US5.3 vs 安智体 R-13） | 安智体 R-13 | 采纳拆分：**首字节前失败** → 自动降级非流式重试一次；**流已开始后失败** → 保留已收内容 + error 事件，不自动重试（避免重复内容） |
| D20 | `--no-*` vs `--skip-*` 命名 | 安智体 R-18 | `--skip-*` 为规范名（与架构 §5.4 一致）；`--no-*` 作为别名接受 |
| D21 | /v1/* OpenAI 兼容面缺失 | 程不宕 §13-1 | **补**：`/v1/models`、`/v1/chat/completions`（流式+非流式）。A4 验收直接依赖，属 Must |
| D22 | /v1/* 错误信封分歧 | 程不宕 §13-13 | **采纳**：`/v1/*` 用 OpenAI 信封（SDK 零改造），`type` 保留 DOMAIN_REASON code；`/api/*` 保持统一错误体。前端只用 `/api/*` |
| D23 | 6 个新配置键 | 程不宕 §13-10 | **批准**（ollama.flash_attention / num_parallel / mps_fallback、chat.num_ctx / max_tokens、server.cors_origins），均有默认值，已并入 04-data-model schema |
| D24 | doctor 磁盘阈值 | 程不宕 T3 | **批准**：<5GB FAIL、<10GB WARN（R5 假设 ≥20GB，阈值保守） |
| D25 | 前端内部文件与 mock | 颜可心 X17 | `web/store.js`、`web/ws.js`、`web/ui/`、`web/mock/` 属实现级细化（架构 §2 为蓝本非穷举）；**`web/mock/` 不进分发包**（build-release.sh 排除） |
| D26 | doctor 留痕 JSONL | 储海量 #4 | MVP 不单独落 doctor-*.jsonl；doctor 输出进 `aife.log` + `--json` 终端输出 |
| D27 | run_log_keep 默认值 | 储海量 #5 | 维持 20（约 2–10MB，见 04-data-model §3.2 估算） |
| D28 | Ollama 版本上限警告 | 储海量 #6 | v1 只做下限（D11）；上限警告列入演进 |
| D29 | mirror 内置清单 | 储海量 #7 / 需求 R1 | v1 内置清单 = 官方源 + 常见社区镜像候选（配置项驱动，不写死）；具体清单在实现定稿并如实标注「社区镜像，可用性不保证」 |
| D30 | 程不宕 T4/T5/T6/T10 | 程不宕 §13 | T4 无取消端点 v1；T5 无应用层 chat 串行锁（bench 观测）；T6 无 API 触发重探针（CLI 覆盖）；T10 fallback 接口预留实现可后补——**全部采纳** |

## 与需求/架构文档的冲突裁决记录

| 冲突 | 双方 | 裁决 | 理由 |
|---|---|---|---|
| US5.3「流式中断自动重试」vs 流式中途重试产生重复内容 | 需求 vs 安智体 | D19 拆分 | 不重试才是对流式用户的正确行为；需求意图是「不让用户干等」，拆分方案满足 |
| 架构配置键 `ollama.num_gpu`（隐含 env）vs Ollama 实际只有请求级 options | 架构 vs 安智体 | 安智体胜 | Ollama 官方文档证实无 `OLLAMA_NUM_GPU` 环境变量；num_gpu 经 /api/chat options 传入（0=CPU/-1=自动） |
| 架构 §4 `ollama.max_loaded_models` vs 实际 env 名 `OLLAMA_MAX_LOADED_MODELS` | 架构 vs 安智体 | 安智体胜 | env 白名单已按官方文档定稿（02-ollama-accel §2.1） |
| 架构 §5.2 无 /v1/* vs 需求 A4 用 OpenAI 风格验收 | 架构 vs 程不宕 | 程不宕胜 | A4 是 Must 验收项，契约必须覆盖 |

—— 高屋建，Phase 2 评审完毕，全部裁决完，进入 Phase 3。
