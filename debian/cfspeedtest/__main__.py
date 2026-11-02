"""Command line entry point: ``cfst <command>`` / ``python3 -m cfspeedtest``."""

import argparse
import json
import sys

from . import __version__, config, core, cron, ddns, engine, links, lock, paths, result
from .log import Logger


def _print_json(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_status(_args):
    cfg = config.load()
    running = lock.is_running()
    state = lock.read_state()
    cores = core.all_core_info(cfg)
    _print_json({
        "running": running,
        "pid": lock.current_run_pid() if running else 0,
        "mode": state.get("mode", ""),
        "phase": "running" if running else state.get("phase", "idle"),
        "started_at": state.get("started_at", 0),
        "finished_at": state.get("finished_at", 0),
        "best_ip": state.get("best_ip", ""),
        "error": state.get("error", ""),
        "cron": cron.current(),
        "core_type": cores["active"],
        "core": cores["cores"][cores["active"]],
        "cores": cores["cores"],
    })


def cmd_cores(_args):
    _print_json(core.all_core_info(config.load()))


def cmd_config(_args):
    _print_json(config.load())


def cmd_nodes(_args):
    cfg = config.load()
    out = []
    for index, item in enumerate(cfg.get("nodes", [])):
        entry = {
            "index": index + 1,
            "name": item.get("name", ""),
            "enabled": bool(item.get("enabled", True)),
            "ip_list": item.get("ip_list", ""),
        }
        try:
            parsed = links.parse_link(item.get("link", ""))
            entry.update({"valid": True, "type": parsed.type,
                          "server": parsed.server, "port": parsed.port})
        except (links.LinkError, ValueError) as exc:
            entry.update({"valid": False, "error": str(exc)})
        out.append(entry)
    _print_json({"nodes": out})


def cmd_update_core(args):
    paths.ensure_dirs()
    cfg = config.load()
    choices = ["active", "all"] + list(core.CORE_TYPES)
    chosen = args.type if args.type in choices else "active"
    if chosen == "active":
        targets = [core.active_type(cfg)]
    elif chosen == "all":
        targets = list(core.CORE_TYPES)
    else:
        targets = [chosen]

    results = {}
    failed = 0
    for target in targets:
        try:
            results[target] = core.update_core(target, tag=args.tag or None, log=print)
        except core.CoreError as exc:
            print("%s 更新失败: %s" % (target, exc))
            results[target] = {"error": str(exc)}
            failed += 1
    _print_json(results)
    return 1 if failed else 0


def cmd_cron(args):
    if args.action == "list":
        _print_json(cron.list_tasks())
        return 0
    cfg = config.load()
    try:
        if args.action == "remove":
            settings = dict(cfg.get("schedule", {}))
            settings["enabled"] = False
            enabled, line = cron.apply(settings)
        else:
            enabled, line = cron.apply(cfg.get("schedule", {}))
    except cron.CronError as exc:
        print("定时任务操作失败: %s" % exc)
        return 1
    _print_json({"enabled": enabled, "line": line})
    return 0


def cmd_ddns(args):
    cfg = config.load()
    nodes = cfg.get("nodes", [])
    rows, when = result.read_result()
    if not rows:
        print("没有可用的测速结果，请先运行测速")
        return 1
    if args.action == "show":
        _print_json(ddns.preview(cfg, nodes, rows, when))
        return 0
    if lock.is_running():
        print("测速正在运行，请等结束后再写入 DNS")
        return 1
    if not (cfg.get("ddns") or {}).get("enabled"):
        print("DDNS 未启用，请先在配置中打开 ddns.enabled")
        return 1
    logger = Logger(paths.DDNS_LOG)
    report = ddns.apply(cfg, nodes, rows, log=logger.log, when=when)
    lock.write_state(ddns=report)
    _print_json(report)
    return 0 if report.get("ok") else 1


def cmd_serve(args):
    from . import web

    web.serve(listen=args.listen, port=args.port)
    return 0


def cmd_run(args):
    mode = args.mode
    if mode == "replace":
        rows, when = result.read_result()
        if not rows:
            print("没有可导出的结果，请先运行测速")
            return 1
        result.export_json(rows, when)
        _print_json({"exported": str(paths.STATE_DIR), "rows": len(rows)})
        return 0
    return engine.run(mode)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cfst",
        description="Cloudflare IP speed test for Debian/Ubuntu (mihomo-powered).",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="run one full test")
    run_parser.add_argument("mode", nargs="?", default="start",
                            choices=["start", "test", "retest", "replace"])
    run_parser.set_defaults(func=cmd_run)

    status_parser = sub.add_parser("status", help="show run status")
    status_parser.set_defaults(func=cmd_status)

    config_parser = sub.add_parser("config", help="print the configuration")
    config_parser.set_defaults(func=cmd_config)

    nodes_parser = sub.add_parser("nodes", help="list configured nodes")
    nodes_parser.set_defaults(func=cmd_nodes)

    update_parser = sub.add_parser("update-core", help="download/upgrade a proxy core")
    update_parser.add_argument(
        "--type", default="active",
        choices=["active", "all", "mihomo", "xray"],
        help="core module to update (default: the active one)")
    update_parser.add_argument("--tag", default="", help="release tag, default latest")
    update_parser.set_defaults(func=cmd_update_core)

    cores_parser = sub.add_parser("cores", help="list proxy core modules")
    cores_parser.set_defaults(func=cmd_cores)

    cron_parser = sub.add_parser("cron", help="apply/remove/list crontab entries")
    cron_parser.add_argument("action", nargs="?", default="apply",
                             choices=["apply", "remove", "list"])
    cron_parser.set_defaults(func=cmd_cron)

    ddns_parser = sub.add_parser("ddns", help="preview or write best IPs to Cloudflare DNS")
    ddns_parser.add_argument("action", nargs="?", default="show",
                             choices=["show", "apply"])
    ddns_parser.set_defaults(func=cmd_ddns)

    serve_parser = sub.add_parser("serve", help="start the web UI")
    serve_parser.add_argument("--listen", default="")
    serve_parser.add_argument("--port", type=int, default=0)
    serve_parser.set_defaults(func=cmd_serve)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
