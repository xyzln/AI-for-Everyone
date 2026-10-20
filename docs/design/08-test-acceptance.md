# AIE（AI For Everyone）测试策略与验收清单 v1.0

- 版本：v1.0（Phase 3 测试侧交付，落盘 `docs/design/08-test-acceptance.md`）
- 作者：凌无缺（测试验收工程师）
- 输入：`01-requirements.md`（§1.2 S1–S7、§7 验收总表 A1–A12、US 全集）、`02-architecture.md`（§6 非功能性）、`03-ollama-accel.md`（§8 V1–V14）、`04-data-model.md`（§7 fixtures FX-01~12、§8 V-01~V-13）、`05-api-contract.md`（§14 V1–V23、错误码全集）、`06-frontend.md`（§8.3 浏览器验收 18 项）
- 诚实边界（贯穿全文）：本验证机为 Windows / Intel Core Ultra 7 265K / 无 NVIDIA GPU / 未装 Ollama。**CPU 路径可真实验证；GPU / NPU / AMD / Apple 路径仅契约级（mock 探测输出断言剖面与启动参数）**，任何测试不得把契约验证写成实测结论。

---

## 1. 测试金字塔与分层策略

| 层 | 工具/框架 | 运行环境要求 | 时长预算 | 占比目标 |
|---|---|---|---|---|
| 单元（Unit） | pytest + stdlib | 无 GPU / 无 Ollama / 无网络 | <30s | 55% |
| 契约（Contract） | pytest + httpx MockTransport + fastapi TestClient | 无 GPU / 无 Ollama / 无网络 | <40s | 30% |
| 集成（Integration） | pytest（标记 `@pytest.mark.integration`） | 需要真实 Ollama + 外网 | 依网络 | 10% |
| 手工（Manual） | 浏览器 + curl | 真实服务 | — | 5%（06 §8.3） |

**分层原则**（继承 Octop 基因）：
1. 单元/契约层不依赖任何外部资源（GPU/Ollama/网络），CI 全量跑；集成层显式标记，CI 可选、本机手动。
2. 确定性逻辑（探测降级链、配置展开、错误码映射、NDJSON 解析）优先单测。
3. 概率性逻辑（模型生成质量）只做探针集断言，不做断言式单元测试。

---

## 2. 测试用例清单（TC-xx）

编号映射：A=验收项、S=成功标准、V=各专项验证清单、FX=数据模型 fixtures、X=前端契约缺口、T=API 契约。

### 2.1 配置层（test_config.py）
- TC-C01 `test_expand_env`：YAML 中 `${VAR}` / `${VAR:-default}` 正确展开（FX-09 envvar）。→ V-01 展开
- TC-C02 `test_validation_fail`：server.port==ollama.port、明文 api_key → 400 CONFIG_INVALID（V-12 / 05 §3）
- TC-C03 `test_hot_reload`：改 models.default 后 reload 不重启生效（V-08 / ADR-003）
- TC-C04 `test_secret_mask`：GET /api/config 中 api_key 恒 `***`（V-09）
- TC-C05 `test_migration_legacy`：legacy 配置（无 config_version + 废弃键）启动自动迁移零操作 + warning + .bak（V-10）
- TC-C06 `test_cross_field`：跨字段校验（port 冲突、mirror=custom 需 mirror_urls）生效

### 2.2 硬件探测（test_hardware.py）
- TC-H01 `test_cpu_fallback`：所有探测工具缺失 → CPU 剖面 + 证据 E3 + 警告含性能预期（FX-04 / A7 / US2.3）
- TC-H02 `test_nvidia_mock`：mock `nvidia-smi`(RTX 4060) → profile=nvidia_cuda、request_options.num_gpu=-1、ollama_env={}（FX-01 / A6 / V3）
- TC-H03 `test_amd_rocm_mock`：mock `rocm-smi` → amd_rocm 剖面（FX-02 / V3）
- TC-H04 `test_amd_vulkan_mock`：mock Windows PnP AMD → amd_vulkan + OLLAMA_VULKAN=1（FX-02 / V4）
- TC-H05 `test_intel_npu_mock`：mock PnP NPU → intel_npu 实验性 caveats、推理走 CPU（FX-03 / D3 / V2）
- TC-H06 `test_evidence_levels`：每个探测结论带 E0–E3 与 source（US2.2 / S3）
- TC-H07 `test_resolved_profile_fields`：ResolvedProfile 含 request_options + catalog_tier（许可研定稿项）

### 2.3 后端契约（test_backend_contract.py）
- TC-B01 `test_missing_model_unhealthy`：mock /api/tags 空 → 后端 unhealthy（M14 教训 / 05 §2.2 / V6）
- TC-B02 `test_fallback_chain`：本地 Ollama 不可用 + openai_compat 启用 → 走 fallback.last_errors 记录原因（US5.4）
- TC-B03 `test_backend_select_atomic`：未知名 400、目标不健康 503、force=true 200、重复选同后端幂等（V17）
- TC-B04 `test_health_pydantic`：BackendHealth 为 pydantic（修正 octop 缺陷）

### 2.4 Ollama 协议（test_ollama_protocol.py）
- TC-P01 `test_ndjson_parse`：/api/pull NDJSON 进度行正确解析为 completed/total（FX-07）
- TC-P02 `test_version_matrix`：/api/version OK/old(<0.5.0)/missing 三种处理（FX-05 / D11）
- TC-P03 `test_tags_models`：/api/tags empty/default/multi/malformed 映射与错误（FX-06）
- TC-P04 `test_error_map`：Ollama 5xx / 连接拒绝 → 正确 AIEError 映射

### 2.5 服务与 API（test_server_api.py）
- TC-S01 `test_unified_error`：全路由注入失败 → `{"error":{code,message,details,trace_id}}`（V1 / ADR-006）
- TC-S02 `test_trace_id`：body.error.trace_id == X-Trace-Id 头（V2）
- TC-S03 `test_422_to_400`：空 messages → 400 VALIDATION（V3）
- TC-S04 `test_404_405`：未知路径 404 ROUTE_NOT_FOUND；错误方法 405 METHOD_NOT_ALLOWED（V4）
- TC-S05 `test_health_deep`：mock Ollama 宕 → deep 恒 200 且 healthy=false（V5）
- TC-S06 `test_pull_409`：连发两次 pull → 第二次 409 PULL_IN_PROGRESS 且 task_id 一致（V9）
- TC-S07 `test_setup_409`：并发 setup → 409 SETUP_RUNNING（V11）
- TC-S08 `test_setup_404`：未 run → 404 SETUP_NOT_FOUND；run 一次后恒 200（V12）
- TC-S09 `test_chat_nonstream`：mock /api/chat → ChatOut 全字段 + usage（V13 / A5）
- TC-S10 `test_openai_compat`：/v1/models、/v1/chat/completions（含 stream chunk + [DONE]），错误用 OpenAI 信封且 code=DOMAIN_REASON（V18 / A4）
- TC-S11 `test_openapi_export`：`aife openapi` 生成 JSON 无悬挂 $ref，HealthReport/BackendHealth 完整（V21）
- TC-S12 `test_config_patch_states`：非法值 400 且文件未改；改 server.port 409 CONFIG_RESTART_REQUIRED；reload 失败 500 且旧配置恢复（V8）
- TC-S13 `test_ws_envelope_seq`：WS 事件含 seq 单调、trace_id；背压可观测（V19 / V20）

### 2.6 流式与中断（test_server_api.py 续 / test_sse.py）
- TC-F01 `test_sse_sequence`：start→delta*→usage→done 严格有序（V14）
- TC-F02 `test_sse_degrade_once`：首 delta 后连接重置 → degrade + 完整 delta + done；重试仍败 → error（V15 / R-13 拆分）
- TC-F03 `test_client_disconnect_cancel`：客户端断开 → 上游 aclose 被调用（V16 / US5.3）

### 2.7 模型与拉取（test_models_manager.py）
- TC-M01 `test_pull_progress_events`：mock pull 进度 → WS model.pull_progress → model.pull_done（V10 / FX-07）
- TC-M02 `test_corrupted_model`：构造损坏 blob → doctor 识别 MODEL_CORRUPTED 并给 remedy（FX-08 / A8）
- TC-M03 `test_delete_404_idempotent`：二次删除 → 404（05 §2.9）

### 2.8 部署与日志（test_bootstrap.py）
- TC-D01 `test_setup_stages`：bootstrap 七阶段（deps/detect/install/configure/pull/verify/start）状态机流转（FX-10）
- TC-D02 `test_jsonl_log`：setup-*.jsonl 含 ts/level/logger/stage/run_id/trace_id/duration_ms/message/event/extra（V-07 / A12）
- TC-D03 `test_skip_stages`：--skip-ollama/--skip-model 断点续跑（US1.2）

### 2.9 前端（06 §8.3 手工，CI 不跑）
- TC-W01~W18：浏览器 18 项 checklist（无 node_modules / 无外部域 / 失败可解释 / 停止保留 / 五态 / 窄屏 / XSS 防护等）

---

## 3. Mock 策略

| 外部依赖 | Mock 手段 | 落点 |
|---|---|---|
| Ollama HTTP | `httpx.MockTransport` 注入响应（FX-05/06/07） | conftest `mock_ollama` fixture |
| 探测工具（nvidia-smi/rocm-smi/PnP） | `monkeypatch` subprocess 返回 FX 原始输出 | conftest `mock_probe` |
| GPU/Ollama/网络 | 均不依赖；集成用例 `@pytest.mark.integration` 跳过 | CI 默认不跑 |
| ~/.aife 状态 | `tmp_path` + `AIE_CONFIG` 环境变量指向临时 config.yaml | conftest `tmp_aife_home` |
| 时间 | `monkeypatch` 冻结 `datetime.now` | conftest `frozen_clock` |

`tests/conftest.py` 关键 fixtures：`tmp_aife_home`（临时 ~/.aife + AIE_CONFIG）、`mock_ollama`（httpx MockTransport 封装，覆盖 /api/version/tags/ps/chat/generate/pull/show/delete）、`frozen_clock`。

---

## 4. 自动化范围与 CI

- **进 CI（全绿门槛）**：TC-C* / TC-H* / TC-B* / TC-P* / TC-S*（除集成）/ TC-F* / TC-M01,M03 / TC-D*。全部无 GPU/Ollama/网络。
- **pytest 标记**：`@pytest.mark.integration`（TC-M02 真实损坏注入、真实 setup 端到端）、`@pytest.mark.slow`（bench）。
- **隔离**：每个测试独立 tmp 配置；OllamaManager 在测试中用 mock transport，不启真实子进程。
- **CI 矩阵**：windows-latest / ubuntu-latest / macos-latest，Python 3.10–3.12（无 GPU runner），超时 10min。
- **门禁**：`python -m pytest -q` 全绿 + `python -m compileall aife` + import 顺序检查。

---

## 5. 验收清单与通过标准（A1–A12）

| # | 验收项 | 通过标准 | 验证等级 | 执行者 |
|---|---|---|---|---|
| A1 | 设备检测输出 | `aife detect --json` 输出本机 CPU 20 核/95.5GB、无 CUDA、profile=cpu，每项带证据等级 | **真实** | 本机 |
| A2 | doctor 体检 | `time aife doctor` ≤30s、五类检查、裸机不崩溃 | **真实** | 本机 |
| A3 | 一键部署冷启动 | 全新环境 `aife setup` 退出码 0、六阶段时间戳、幂等 | **真实**（CPU，依赖网络） | 本机/目标机 |
| A4 | 服务与 API 契约 | serve 后 `curl /v1/models` 200 含默认模型 | **真实** | 本机 |
| A5 | 模型推理测试 | `aife chat "你好，请用一句话介绍你自己"` 首 token ≤10s、非空中文 | **真实** | 本机 |
| A6 | GPU 剖面契约 | mock nvidia-smi(4060) → profile=cuda、num_gpu=-1、env={} | **契约** | CI |
| A7 | CPU 回退契约 | 本机 setup 输出 CPU 警告、流程不中断 | **真实** | 本机 |
| A8 | 模型拉取与验证 | pull→list→探针 200 非空；损坏模型 doctor 识别 | **真实+契约** | 本机/CI |
| A9 | 分平台打包产物 | 三分平台 zip + SHA256SUMS 校验通过 | **真实**（win）/契约（mac/linux） | 打包脚本 |
| A10 | GitHub 上传包 | ≤100MB、含 LICENSE/README、解压可 setup | **真实**（win） | 打包脚本 |
| A11 | 全量测试无 GPU | `pytest` 全绿，无 GPU/Ollama/网络 | **真实** | CI/本机 |
| A12 | 启动日志结构 | setup-*.jsonl 含全部字段 | **真实** | 本机 |

**成功标准 S1–S7 测量**：S1 冷启动计时（A3）、S2 一次跑通率（setup JSONL 聚合）、S3 检测正确率（A1 抽检）、S4 doctor 时效（A2 time）、S5 推理延迟（A5 首 token）、S6 包完整性（A9 checksum）、S7 无 GPU 可测（A11）。

### 目标机验收清单（随包分发 `docs/target-machine-checklist.md`）
GPU/NPU/Apple 路径用户在本机执行：① `aife detect --json` 确认剖面；② `aife doctor`；③ `aife setup`（拉模型）；④ `aife chat` 测首 token 延迟与 tok/s；⑤ 记录实测数字回填 README。本交付不提供 GPU 实测数字。

---

## 6. 缺陷分级与放行门禁

| 级别 | 定义 | 示例 | 处理 |
|---|---|---|---|
| Blocker | 核心路径不可用 / 数据丢失风险 | setup 在支持矩阵内失败、detect 崩溃 | 必须修，阻塞发布 |
| Major | 功能缺陷但可绕过 | 某 WS 事件缺字段、doctor 某检查误报 | 发布前修或显式记录 |
| Minor | 体验/文档问题 | 文案、日志格式 | 可后续 |

**Release Gate**：① CI 全绿（无 GPU/Ollama/网络）；② A1–A12 真实项全过（本机）；③ 三分平台包 + SHA256SUMS 通过；④ README「未实测路径诚实声明」齐全；⑤ 大小预算（GitHub 包 ≤100MB）断言通过。

---

## 7. 性能测试最小集

| 指标 | 目标 | 测量方法 | 分工 |
|---|---|---|---|
| CLI 冷启动 P50 | <0.8s | `time aife detect` | 本机 |
| serve 可接受请求 | <3s | 启动后 curl /api/health | 本机 |
| doctor | <30s | `time aife doctor` | 本机 |
| TTFT（CPU/3B） | ≤10s | `aife chat` 计时首 token | 本机（依赖网络拉模型） |
| aife-server RSS | <150MB（不含 Ollama） | 任务管理器/psutil | 本机 |
| 包体积 | GitHub 包 ≤100MB | `build-release.sh` 断言 | 打包 |

---

## 8. 风险与缺口

| # | 风险 | 应对 |
|---|---|---|
| R-T1 | GPU/NPU 实测加速无法在本机验证 | 契约测试 + 目标机清单，README 诚实声明 |
| R-T2 | 国内网络拉模型/装 Ollama 可能失败 | 分阶段重试 + mirror/代理配置点（D1）+ doctor 诊断 |
| R-T3 | WebSocket 真实收发边界（背压/重连） | 单连接测试 + 端到端手工（06 §8.3 #16） |
| R-T4 | 模型生成质量非确定性 | 仅探针集 P1–P4 4/4 判可用，不做断言式单测 |
| R-T5 | 集成测试依赖外网，CI 不稳定 | 标记 `@integration`，CI 跳过，本机手动 |

> 本文与 05-api-contract 的 23 条 V 清单、04 的 FX  fixtures、03 的 V 清单、06 的浏览器 checklist 完全对齐；无新增契约缺口（X1–X3/X6/X7 已由 05 §2.18/§4.5 定型覆盖）。
