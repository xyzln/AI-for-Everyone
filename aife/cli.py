"""AIE command-line interface (02-architecture §5.4).

Subcommands: version, detect, doctor, setup, serve, desktop, chat, models,
backend, bench, openapi. Heavy imports (server, runtime) are lazy so
lightweight commands stay fast and importable even when optional deps are
missing. ``desktop`` additionally imports ``pywebview`` lazily and falls back
to the browser when the optional dependency / WebView2 runtime is absent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Optional


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aife",
        description="AI For Everyone - one-command local LLM deployment",
    )
    p.add_argument("--version", action="store_true", help="打印版本并退出")
    p.add_argument("--config", help="指定配置文件路径")

    sub = p.add_subparsers(dest="command")

    sub.add_parser("version", help="打印版本")

    detect = sub.add_parser("detect", help="探测硬件并输出加速剖面")
    detect.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor", help="环境体检")
    doctor.add_argument("--json", action="store_true")

    setup = sub.add_parser("setup", help="一键部署")
    setup.add_argument("--skip-deps", action="store_true")
    setup.add_argument("--skip-ollama", action="store_true")
    setup.add_argument("--skip-model", action="store_true")
    setup.add_argument("--model", help="指定默认模型")
    setup.add_argument("--dry-run", action="store_true")
    setup.add_argument("--serve", action="store_true", help="部署完成后启动服务")

    serve = sub.add_parser("serve", help="启动 aife-server")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--no-browser", action="store_true")
    serve.add_argument("--window", action="store_true",
                       help="原生桌面窗口运行（pywebview；不可用时回退浏览器）")

    desktop = sub.add_parser("desktop", help="启动原生桌面窗口（打包版默认入口）")
    desktop.add_argument("--host")
    desktop.add_argument("--port", type=int)
    desktop.add_argument("--no-tray", action="store_true",
                         help="禁用系统托盘（覆盖配置 desktop.tray）")

    chat = sub.add_parser("chat", help="命令行对话")
    chat.add_argument("--model", "-m", help="模型名")
    chat.add_argument("--message", "-M", help="单条消息（不指定则进入交互）")
    chat.add_argument("--stream", action="store_true")

    models = sub.add_parser("models", help="模型管理")
    msub = models.add_subparsers(dest="models_cmd")
    msub.add_parser("list", help="列出已安装模型")
    mpull = msub.add_parser("pull", help="拉取模型")
    mpull.add_argument("name")
    mrm = msub.add_parser("rm", help="删除模型")
    mrm.add_argument("name")
    mshow = msub.add_parser("show", help="查看模型详情")
    mshow.add_argument("name")

    backend = sub.add_parser("backend", help="推理后端管理")
    bsub = backend.add_subparsers(dest="backend_cmd")
    bsub.add_parser("list", help="列出后端")
    buse = bsub.add_parser("use", help="切换后端")
    buse.add_argument("name")
    bsub.add_parser("doctor", help="后端健康检查")

    bench = sub.add_parser("bench", help="本地压测")
    bench.add_argument("--model", "-m")
    bench.add_argument("--duration", "-d", type=int, default=30)
    bench.add_argument("--concurrency", "-c", type=int, default=1)

    openapi = sub.add_parser("openapi", help="导出 OpenAPI schema")
    openapi.add_argument("--out", help="写出到文件")

    return p


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_version(_args) -> int:
    from . import __version__
    print(__version__)
    return 0


def cmd_detect(args) -> int:
    from .hardware import build_report, resolve_profile
    from .config import load_config

    cfg = load_config(args.config)
    resolved = resolve_profile(explicit_device=cfg.hardware.device)
    report = build_report(resolved)
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(f"加速剖面: {resolved.profile_id} ({resolved.device_kind_name})")
        print(f"  catalog_tier: {resolved.catalog_tier}")
        print(f"  env: {resolved.ollama_env or '{}'}")
        print(f"  request_options: {resolved.request_options}")
        print(f"  系统 RAM: {report.system_ram_gb} GiB，逻辑核数: {report.cpu_cores}")
        for w in resolved.warnings:
            print(f"  [!] {w}")
    return 0


def cmd_doctor(args) -> int:
    from .runtime import get_runtime

    rt = get_runtime()
    checks = []

    py_ok = sys.version_info >= (3, 10)
    checks.append(("python", py_ok, sys.version.split()[0], "error"))

    missing = []
    for mod in ["fastapi", "uvicorn", "httpx", "pydantic", "yaml", "websockets"]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    checks.append(("deps", not missing, "OK" if not missing else f"缺失: {missing}", "error"))

    checks.append(("config", True, f"config_version {rt.cfg.config_version}", "error"))

    installed = rt.manager.is_installed()
    checks.append(("ollama", installed, rt.manager.binary_version() or "未安装",
                   "warn" if not installed else "ok"))
    if installed:
        ok, remedy = rt.manager.check_version()
        checks.append(("ollama_version", ok, remedy or rt.manager.state.version or "",
                       "error" if not ok else "ok"))

    checks.append(("hardware", True, f"{rt.resolved.profile_id} ({rt.resolved.device_kind_name})",
                   "info"))

    if args.json:
        out = [{"name": n, "ok": ok, "detail": d, "severity": sev} for (n, ok, d, sev) in checks]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for name, ok, detail, sev in checks:
            mark = "OK" if ok else ("WARN" if sev == "warn" else "FAIL")
            print(f"[{mark}] {name:14s} {detail}")

    failed = [n for (n, ok, _, sev) in checks if sev == "error" and not ok]
    return 1 if failed else 0


def cmd_setup(args) -> int:
    from .bootstrap import run_setup
    from .runtime import get_runtime

    rt = get_runtime()
    if args.model:
        rt.cfg.models.default = args.model
    skip = []
    if args.skip_deps:
        skip.append("deps")
    if args.skip_ollama:
        skip.append("ollama")
    if args.skip_model:
        skip.append("model")

    events = []

    def _on_event(etype, payload):
        events.append((etype, payload))
        if etype == "setup.step_progress":
            print(f"  * {payload.get('step')}: {payload.get('message','')}", flush=True)
        elif etype == "setup.step_done":
            print(f"  [ok] {payload.get('step')} 完成 ({payload.get('duration_ms',0)}ms)", flush=True)
        elif etype == "setup.error":
            print(f"  [fail] {payload.get('step')} 失败: {payload.get('message')}", flush=True)
            if payload.get("remedy"):
                print(payload["remedy"], flush=True)
        elif etype == "model.pull_progress":
            p = payload
            tot = p.get("total")
            if tot:
                pct = int(p["completed"] / tot * 100)
                print(f"  .. {p.get('model')} {pct}%", end="\r", flush=True)

    rt.bus.subscribe(lambda ev: _on_event(ev["type"], ev["payload"]))

    record = asyncio.run(run_setup(rt, skip=skip, dry_run=args.dry_run))
    print(f"\n部署结果: {record['status']}")
    if args.serve and record["status"] == "done" and not args.dry_run:
        return cmd_serve_inner(rt)
    return 0 if record["status"] in ("done",) else 1


def cmd_desktop(args) -> int:
    from .desktop import run_window
    from .runtime import get_runtime

    rt = get_runtime()
    # --no-tray 覆盖配置关托盘；缺省 None = 跟随 rt.cfg.desktop.tray
    tray = False if getattr(args, "no_tray", False) else None
    try:
        asyncio.run(run_window(rt, args.host, args.port, tray=tray))
    except KeyboardInterrupt:
        return 130
    return 0


def cmd_serve(args) -> int:
    from .runtime import get_runtime
    return cmd_serve_inner(get_runtime(), args)


def cmd_serve_inner(rt, args=None) -> int:
    host = (args and args.host) or rt.cfg.server.host
    port = (args and args.port) or rt.cfg.server.port
    no_browser = (args and getattr(args, "no_browser", False)) or False

    if args and getattr(args, "window", False):
        from .desktop import run_window
        try:
            asyncio.run(run_window(rt, host, port))
        except KeyboardInterrupt:
            return 130
        return 0

    import webbrowser

    import uvicorn

    url = f"http://{host}:{port}"
    print(f"AIE 服务已启动: {url}  (Ctrl+C 退出)")
    if rt.cfg.server.open_browser and not no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        uvicorn.run("aife.server.app:app", host=host, port=port,
                    log_level=rt.cfg.server.log_level, access_log=False)
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


def cmd_chat(args) -> int:
    from .runtime import get_runtime

    rt = get_runtime()
    backend = rt.registry.current()
    if backend is None:
        print("无活跃后端", file=sys.stderr)
        return 1
    model = args.model or rt.cfg.models.default
    if not model:
        from .models.catalog import recommend
        model = recommend(rt.resolved)

    messages = []
    if args.message:
        messages.append({"role": "user", "content": args.message})
        out = _chat_once(rt, backend, model, messages, args.stream)
        print(out)
        return 0

    print(f"与 {model} 对话（输入 exit 退出）")
    while True:
        try:
            line = input("you> ")
        except (EOFError, KeyboardInterrupt):
            break
        if line.strip().lower() in ("exit", "quit"):
            break
        messages.append({"role": "user", "content": line})
        reply = _chat_once(rt, backend, model, messages, args.stream)
        print(f"ai> {reply}")
        messages.append({"role": "assistant", "content": reply})
    return 0


def _chat_once(rt, backend, model, messages, stream):
    parts = []

    async def _run():
        async for ev in backend.chat(model=model, messages=messages, stream=stream):
            if ev.get("delta"):
                parts.append(ev["delta"])
                if stream:
                    print(ev["delta"], end="", flush=True)
        if stream:
            print()

    asyncio.run(_run())
    return "".join(parts)


def cmd_models(args) -> int:
    from .runtime import get_runtime

    rt = get_runtime()
    cmd = args.models_cmd
    if cmd == "list":
        models = asyncio.run(rt.model_manager.list_installed())
        for m in models:
            print(f"{m.name}\t{m.parameter_size}\t{m.quantization}\t{m.size // (1024*1024)}MB")
        return 0
    if cmd == "pull":
        try:
            tid = rt.model_manager.pull(args.name)
        except Exception as exc:
            print(f"拉取失败: {exc}", file=sys.stderr)
            return 1
        print(f"开始拉取 {args.name} (task {tid})")
        return 0
    if cmd == "rm":
        asyncio.run(rt.model_manager.delete(args.name))
        print(f"已删除 {args.name}")
        return 0
    if cmd == "show":
        info = asyncio.run(rt.model_manager.show(args.name))
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    print("用法: aife models list|pull NAME|rm NAME|show NAME", file=sys.stderr)
    return 1


def cmd_backend(args) -> int:
    from .runtime import get_runtime

    rt = get_runtime()
    cmd = args.backend_cmd
    if cmd == "list":
        snap = asyncio.run(rt.registry.snapshot())
        print(f"active: {snap.active}")
        for name, st in snap.backends.items():
            print(f"  {name:14s} {'OK' if st.healthy else 'DOWN'}  {st.detail}")
        return 0
    if cmd == "use":
        if args.name not in rt.registry._backends:
            print(f"未知后端: {args.name}", file=sys.stderr)
            return 1
        rt.registry.switch_to(args.name, "cli")
        print(f"已切换至 {args.name}")
        return 0
    if cmd == "doctor":
        snap = asyncio.run(rt.registry.snapshot())
        for name, st in snap.backends.items():
            print(f"{name}: {'OK' if st.healthy else 'DOWN'} - {st.detail}")
        return 0
    print("用法: aife backend list|use NAME|doctor", file=sys.stderr)
    return 1


def cmd_bench(args) -> int:
    from .runtime import get_runtime

    rt = get_runtime()
    backend = rt.registry.current()
    if backend is None:
        print("无活跃后端", file=sys.stderr)
        return 1
    model = args.model or rt.cfg.models.default
    if not model:
        from .models.catalog import recommend
        model = recommend(rt.resolved)
    print(f"基准测试 {model}（{args.duration}s）...（最小实现）")
    # Minimal: one warm call to measure time-to-first-token.
    import time

    start = time.time()
    text = _chat_once(rt, backend, model, [{"role": "user", "content": "用一句话介绍你自己。"}], stream=False)
    elapsed = time.time() - start
    n_tokens = max(1, len(text) // 2)
    print(f"首轮: {elapsed:.2f}s，约 {n_tokens/elapsed:.1f} tok/s（中文按 ~2 字符/token 估算）")
    return 0


def cmd_openapi(args) -> int:
    from .server.app import app

    schema = app.openapi()
    text = json.dumps(schema, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"已写出 OpenAPI schema 到 {args.out}")
    else:
        print(text)
    return 0


def _force_utf8_io() -> None:
    """Force UTF-8 on stdout/stderr.

    Legacy Windows consoles use GBK/cp936 and raise UnicodeEncodeError on
    symbols like check/warning marks, crashing the CLI. We reconfigure to
    UTF-8; if that is unavailable (some frozen runtimes), we re-wrap the raw
    buffer with a UTF-8 TextIOWrapper as a guaranteed fallback.
    """
    import io
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
            continue
        except Exception:
            pass
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            try:
                setattr(sys, name, io.TextIOWrapper(
                    buffer, encoding="utf-8", errors="replace",
                    line_buffering=getattr(stream, "line_buffering", False),
                ))
            except Exception:
                pass


def main(argv: Optional[list[str]] = None) -> int:
    # Windows 控制台默认代码页（如 GBK/cp936）无法编码 ✓ ⚠ ↓ 等符号，
    # 会抛 UnicodeEncodeError 崩溃；统一改为 UTF-8 + 容错，保证打包后可直跑。
    _force_utf8_io()

    parser = _build_parser()
    args = parser.parse_args(argv)

    # 显式 --config 覆盖环境变量：load_config()/_resolve_path(None) 会读
    # $AIE_CONFIG，因此 serve/backend/chat/models/setup/doctor 等所有走
    # get_runtime() 的命令也统一 honor --config（与 detect 的显式路径一致）。
    if getattr(args, "config", None):
        os.environ["AIE_CONFIG"] = args.config

    if args.version:
        return cmd_version(args)
    if args.command is None:
        parser.print_help()
        return 0

    dispatch = {
        "version": cmd_version,
        "detect": cmd_detect,
        "doctor": cmd_doctor,
        "setup": cmd_setup,
        "serve": cmd_serve,
        "desktop": cmd_desktop,
        "chat": cmd_chat,
        "models": cmd_models,
        "backend": cmd_backend,
        "bench": cmd_bench,
        "openapi": cmd_openapi,
    }
    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    try:
        return handler(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
