"""CLI 入口。

  python3 -m weatherwall init          初始化(探测区域并写入默认配置)
  python3 -m weatherwall once          执行一轮(默认不切壁纸, 加 --apply 才切)
  python3 -m weatherwall daemon        仅后台循环(无设置页)
  python3 -m weatherwall serve         设置后台+后台循环(默认, 推荐)
  python3 -m weatherwall status        查看状态
  python3 -m weatherwall set-wallpaper <file>  手动设置某张壁纸
"""

import argparse
import json
import sys

from . import config
from .app import App


def cmd_init(args) -> int:
    config.ensure_dirs()
    cfg = config.load_config()
    from . import region
    detected = region.probe_region(cfg, force=True)
    if detected:
        cfg.setdefault("region", "auto")
        print(f"网络探测: google {'可达' if detected == 'global' else '不可达'} -> "
              f"通道: {'国外(global)' if detected == 'global' else '国内(china)'}")
    if not config.config_file().exists():
        config.save_config(cfg)
    print(f"配置文件: {config.config_file()}")
    print(f"基准图目录: {config.base_images_dir()}")
    print(f"壁纸缓存目录: {config.cache_dir()}")
    if not cfg.get("base_image"):
        print("提示: 尚未配置基准图，可启动 serve 后在设置后台上传")
    return 0


def cmd_once(app: App, args) -> int:
    result = app.run_guarded(apply=args.apply)
    if not result:
        print(f"失败: {app.state.get('last_error')}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_serve(app: App, args) -> int:
    import socket
    import time

    from . import server
    cfg = config.load_config()
    host = args.host or cfg["server"]["host"]
    port = args.port or cfg["server"]["port"]

    # 单实例保护: 已有实例在监听则本进程挂起(避免 launchd 重启/双击导致重复调度)
    if host in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", int(port))) == 0:
                print(f"已有实例运行于 127.0.0.1:{port}，本进程挂起待命")
                while True:
                    time.sleep(3600)

    app.start_scheduler()
    server.serve(app, host, port)
    return 0


def cmd_daemon(app: App, args) -> int:
    app.start_scheduler()
    try:
        import time
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        app.stop()
    return 0


def cmd_status(app: App, args) -> int:
    print(json.dumps(app.status(), ensure_ascii=False, indent=2))
    return 0


def cmd_set_wallpaper(app: App, args) -> int:
    from .wallpaper import set_wallpaper
    from pathlib import Path
    try:
        set_wallpaper(Path(args.file))
        print(f"已设置壁纸: {args.file}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"失败: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="weatherwall",
                                     description="动态天气壁纸: 温度+时间+天气 -> AI 生图 -> 自动切换")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="初始化: 探测区域并生成默认配置")
    sub.add_parser("status", help="查看运行状态")

    p_once = sub.add_parser("once", help="执行一轮流程")
    p_once.add_argument("--apply", action="store_true", help="允许切换系统壁纸")

    sub.add_parser("daemon", help="仅后台循环(无设置页)")

    p_serve = sub.add_parser("serve", help="设置后台 + 后台循环(推荐)")
    p_serve.add_argument("--host", help="默认读配置 server.host")
    p_serve.add_argument("--port", type=int, help="默认读配置 server.port")

    p_set = sub.add_parser("set-wallpaper", help="手动设置壁纸")
    p_set.add_argument("file")

    args = parser.parse_args()

    if args.cmd == "init":
        return cmd_init(args)

    app = App()
    if args.cmd == "once":
        return cmd_once(app, args)
    if args.cmd == "daemon":
        return cmd_daemon(app, args)
    if args.cmd == "serve":
        return cmd_serve(app, args)
    if args.cmd == "status":
        return cmd_status(app, args)
    if args.cmd == "set-wallpaper":
        return cmd_set_wallpaper(app, args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
