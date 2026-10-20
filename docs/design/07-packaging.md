# AIE（AI For Everyone）打包分发设计 v1.0

- 版本：v1.0（Phase 3 交付保障，落盘 `docs/design/07-packaging.md`）
- 作者：陆上线（部署运维工程师）
- 输入：`01-requirements.md`（US7.1/7.2、A9/A10）、`02-architecture.md`（ADR-005、§6 分发 ≤30MB、scripts/、.github/workflows/ci.yml）、`04-data-model.md`（~/.aife 布局）、`05-api-contract.md`（/healthz、/api/health/deep）、`06-frontend.md`（X17：web/mock/ 不进分发包）、`00-decisions.md`（D2 不含 Ollama 二进制/模型权重、D29 mirror 配置驱动不编造清单）

---

## 1. 发布产物矩阵

| 产物 | 定位 | 目标用户 | 大小预算 | 内容 |
|---|---|---|---|---|
| `aife-<ver>-win-x64.zip` | Windows 分发包 | Windows 桌面用户 | ≤30MB | 源码 + scripts/install-windows.ps1 + config/ + README |
| `aife-<ver>-macos-arm64.zip` | macOS 分发包 | Apple Silicon 用户 | ≤30MB | 源码 + scripts/install-macos.sh + config/ + README |
| `aife-<ver>-linux-x64.zip` | Linux 分发包 | Linux 用户 | ≤30MB | 源码 + scripts/install-linux.sh + config/ + README |
| `aife-<ver>-source.zip` | **GitHub 上传包** | 开发者/开源分发 | **≤100MB（硬约束）** | 完整仓库（不含 venv/runs/__pycache__/web/mock/.pytest_cache/.git） |
| `SHA256SUMS` | 完整性校验 | 所有用户 | — | 上述四个 zip 的 sha256 |

**明确不含**：Ollama 二进制、模型权重、venv、__pycache__、runs/、web/mock/、.pytest_cache、.git。理由：D2（权重/二进制不入包，降低体积与许可风险）；模型与 Ollama 由 `aife setup` 首次运行时按平台下载。

---

## 2. zip 内部目录结构（解压后）

```
aife/                              # 解压根（与仓库根一致）
├── pyproject.toml
├── README.md                      # 快速开始 + 三平台安装 + 诚实声明
├── LICENSE                        # MIT
├── .gitignore
├── config/
│   └── aife.yaml                  # 配置模板
├── aife/                          # 主包
├── web/                           # 零构建前端（不含 mock/）
├── scripts/
│   ├── install-windows.ps1
│   ├── install-linux.sh
│   ├── install-macos.sh
│   └── build-release.sh
├── tests/                         # 测试（GitHub 包保留，便于开发者跑）
└── .github/workflows/ci.yml
```

---

## 3. 三平台安装脚本规格

通用原则（继承 Octop 基因）：幂等、失败给可复制修复命令、输出「下一步执行什么」。**不引入 PyInstaller/Docker/代码签名**（ADR-005 + D2）。

### 3.1 scripts/install-windows.ps1（PowerShell）
- 严格模式：`Set-StrictMode -Version Latest; $ErrorActionPreference='Stop'`。
- 检测 Python 3.10–3.12：`py --list` 或 `python --version`；缺失 → 提示下载官方 installer 链接并退出 1。
- 创建 venv：`python -m venv .venv`（项目内 .venv，便于卸载回滚）。
- 安装：`& .venv/Scripts/pip install -e .`（开发可编辑）或 `pip install .`。
- 可用性：venv Scripts 加入当前 session PATH；提示「重新打开终端或执行 `.venv/Scripts/Activate.ps1`」。
- 幂等：检测 `.venv` 已存在则跳过创建；`aife --version` 成功即认为已装。
- 完成提示：`aife setup` 启动一键部署。

### 3.2 scripts/install-linux.sh / install-macos.sh（bash）
- `set -euo pipefail`。
- 同 windows 的 Python 检测 / venv / pip install / 幂等逻辑。
- macOS：安装后若 Ollama 因 Gatekeeper 拦截，提示 `xattr -d com.apple.quarantine`（R10）。
- 二者共用函数，差异仅在 `aife` 命令可用性提示（mac/linux 用 `source .venv/bin/activate`）。

---

## 4. scripts/build-release.sh 规格

功能：提取版本 → 组装 staging → 按排除规则打包四个 zip → 生成 SHA256SUMS → **大小预算断言**（超限即失败）→ 输出产物清单。

- 版本提取：`grep __version__ aife/__init__.py` 或 `python -c "import aife; print(aife.__version__)"`。
- 排除规则（rsync --exclude 或 zip -x）：`.venv/ __pycache__/ *.pyc runs/ web/mock/ .pytest_cache/ .git/ .gitignore 外的缓存 / dist/`。
- zip 生成：优先 `zip -r`；缺失则 `python -c "import shutil; shutil.make_archive(...)"` fallback。
- 大小断言：`stat -c%s` 超阈值 → `echo "ERROR: ... exceeds budget" >&2; exit 1`。
- 产物落 `dist/`，并生成 `dist/SHA256SUMS`（GNU `sha256sum` 或 `python` 实现）。

---

## 5. CI/CD

### 5.1 .github/workflows/ci.yml
- 触发：push / PR。
- 矩阵：windows-latest / ubuntu-latest / macos-latest；Python 3.10–3.12。
- 步骤：checkout → setup-python → `pip install -e .[test]`（test extra 含 pytest）→ `python -m compileall aife` → `python -m pytest -q`（无 GPU/Ollama/网络；integration 标记跳过）。

### 5.2 .github/workflows/release.yml
- 触发：`push tags v*`。
- 步骤：跑测试 → `bash scripts/build-release.sh` → `gh release create` 上传四个 zip + SHA256SUMS → 自动生成 release notes（含诚实声明链接）。

---

## 6. GitHub 上传包合规检查单
- [ ] `aife-<ver>-source.zip` ≤100MB
- [ ] 含 LICENSE / README / .gitignore / ci.yml
- [ ] 无大文件（>10MB 单文件告警）
- [ ] 无密钥（grep -r "sk-" / "api_key:" 仅 ${VAR} 引用）
- [ ] git 干净：无 .venv / runs / __pycache__ 提交

---

## 7. 冒烟验收
- Windows（真实）：解压 → `powershell -ExecutionPolicy Bypass -File scripts/install-windows.ps1` → `aife detect --json` 非空 → `aife doctor` 不崩溃。
- macOS / Linux（静态审查 + 脚本 dry-run）：`bash -n scripts/install-linux.sh` 语法检查；在无 Ollama 容器环境跑 `aife --version` / `aife openapi >/dev/null`。

---

## 8. 卸载 / 回滚
- 卸载：`rm -rf <项目>/.venv` + `rm -rf ~/.aife`（删除 ~/.aife 即清除 AIE 全部自有状态，模型在 OLLAMA_MODELS 需用户单独处置）。满足「卸载可回滚」承诺（P1 画像）。
- 回滚配置：`~/.aife/config.yaml.bak` 一键恢复。
