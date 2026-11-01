"""Small stdlib-only web server and JSON API.

Security defaults: bind to 127.0.0.1, no directory listing, optional bearer
token.  If the token is empty, anyone who can reach the port can start/stop
tests and read node links, so keep the default loopback bind unless the port
is protected by a reverse proxy.
"""

import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, config, core, cron, links, lock, paths, result
from .log import Logger, read_chunk

MAX_BODY = 2 * 1024 * 1024
_cron_cache = {"ts": 0.0, "info": {"installed": False, "line": ""}}
_core_update = {"updating": False, "type": "", "message": "", "error": "", "finished_at": 0}
_core_update_lock = threading.Lock()


def _json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _cron_status(force=False):
    now = time.time()
    if force or now - _cron_cache["ts"] > 15:
        _cron_cache["ts"] = now
        _cron_cache["info"] = cron.current()
    return _cron_cache["info"]


def _parse_link_summary(item, index):
    name = (item.get("name") or "").strip()
    summary = {
        "index": index + 1,
        "name": name,
        "ip_list": (item.get("ip_list") or "").strip(),
        "enabled": bool(item.get("enabled", True)),
        "valid": False,
        "type": "",
        "server": "",
        "port": 0,
        "error": "",
    }
    try:
        parsed = links.parse_link(item.get("link", ""))
    except (links.LinkError, ValueError) as exc:
        summary["error"] = str(exc)
        return summary
    summary.update({"valid": True, "type": parsed.type,
                    "server": parsed.server, "port": parsed.port})
    if not name:
        summary["name"] = parsed.name
        summary["name_suggested"] = True
    return summary


def _config_warnings(cfg):
    warnings = []
    core_type = core.active_type(cfg)
    enabled_nodes = [item for item in cfg.get("nodes", []) if item.get("enabled", True)]
    if not enabled_nodes:
        warnings.append("没有启用任何节点，测速无法开始")
    for index, item in enumerate(enabled_nodes, start=1):
        try:
            parsed = links.parse_link(item.get("link", ""))
        except (links.LinkError, ValueError) as exc:
            warnings.append("节点 %s 链接无效: %s" % (item.get("name") or index, exc))
            continue
        try:
            core.validate_proxy(parsed.proxy, core_type)
        except core.CoreError as exc:
            warnings.append("节点 %s 与当前内核不兼容: %s" % (item.get("name") or index, exc))
    if cfg.get("ip_source") == "custom_file" and cfg.get("custom_ip_file"):
        if not Path(cfg["custom_ip_file"]).exists():
            warnings.append("自定义 IP 列表文件不存在: %s" % cfg["custom_ip_file"])
    configured_paths = (cfg.get("core") or {}).get("paths") or {}
    for name, path in configured_paths.items():
        if path and not Path(path).exists():
            warnings.append("%s 的自定义内核路径不存在: %s" % (name, path))
    if not core.core_info(cfg, core_type).get("installed"):
        warnings.append("当前内核 %s 尚未安装，请到「内核」页安装" % core_type)
    return warnings


class Handler(BaseHTTPRequestHandler):
    server_version = "cf-speedtest/%s" % __version__

    # ── helpers ─────────────────────────────────────────────────────────
    def log_message(self, fmt, *args):
        # Never leak a token passed as ?token= into the service log.
        message = fmt % args
        message = re.sub(r"token=[^&\s\"]+", "token=***", message)
        sys.stderr.write("%s - %s\n" % (self.address_string(), message))

    def _headers(self, status=200, content_type="application/json; charset=utf-8",
                 length=0, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _send_json(self, payload, status=200):
        data = _json_bytes(payload)
        self._headers(status, length=len(data))
        self.wfile.write(data)

    def _send_error(self, status, message):
        self._send_json({"error": message}, status=status)

    def _token(self):
        return (config.load(create=False).get("web") or {}).get("token", "")

    def _authorized(self):
        token = self._token()
        if not token:
            return True
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        supplied = (
            self.headers.get("X-CFST-Token", "")
            or (query.get("token") or [""])[0]
        )
        if not supplied:
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                supplied = auth[7:].strip()
        return bool(supplied) and secrets.compare_digest(supplied, token)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("invalid JSON body")
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _serve_file(self, path, download_name=None, cache=True):
        try:
            data = path.read_bytes()
        except OSError:
            self._send_error(404, "not found")
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        extra = {}
        if download_name:
            extra["Content-Disposition"] = 'attachment; filename="%s"' % download_name
        if cache:
            extra["Cache-Control"] = "public, max-age=86400"
        else:
            extra["Cache-Control"] = "no-cache"
        self._headers(200, content_type, len(data), extra)
        self.wfile.write(data)

    def _static(self, url_path):
        relative = urllib.parse.unquote(url_path.lstrip("/")) or "index.html"
        if relative.endswith("/"):
            relative += "index.html"
        target = (paths.WEB_DIR / relative).resolve()
        try:
            target.relative_to(paths.WEB_DIR.resolve())
        except ValueError:
            self._send_error(403, "forbidden")
            return
        if not target.is_file():
            self._send_error(404, "not found")
            return
        cache = "/vendor/" in url_path
        self._serve_file(target, cache=cache)

    # ── HTTP methods ───────────────────────────────────────────────────
    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        route = parsed.path

        if route == "/api/ping":
            self._send_json({"ok": True, "auth_required": bool(self._token()),
                             "version": __version__})
            return

        if route.startswith("/api/"):
            if not self._authorized():
                self._send_error(401, "unauthorized")
                return
            try:
                self._api_get(route, urllib.parse.parse_qs(parsed.query))
            except Exception as exc:  # never kill the server on a bad request
                self._send_error(500, str(exc))
            return

        self._static(route)

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        route = parsed.path
        if not route.startswith("/api/"):
            self._send_error(404, "not found")
            return
        if not self._authorized():
            self._send_error(401, "unauthorized")
            return
        try:
            body = self._read_body()
        except ValueError as exc:
            self._send_error(400, str(exc))
            return
        try:
            self._api_post(route, body)
        except Exception as exc:
            self._send_error(500, str(exc))

    # ── API: GET ───────────────────────────────────────────────────────
    def _api_get(self, route, query):
        if route == "/api/status":
            self._send_json(self._status())
        elif route == "/api/config":
            self._send_json({"config": config.load()})
        elif route == "/api/nodes":
            cfg = config.load()
            self._send_json({
                "nodes": [_parse_link_summary(item, index)
                          for index, item in enumerate(cfg.get("nodes", []))],
                "ip_lists": cfg.get("ip_lists", []),
            })
        elif route == "/api/best":
            rows, when = result.read_result()
            self._send_json({
                "content": result.best_view(rows, when),
                "payload": result.build_payload(rows, when),
            })
        elif route == "/api/history":
            history = result.parse_history()
            if not history:
                history = result.history_from_result_files()
            self._send_json({"history": history})
        elif route == "/api/log":
            try:
                pos = int((query.get("pos") or ["0"])[0])
            except ValueError:
                pos = 0
            tail = 262144 if pos == 0 else 0
            self._send_json(read_chunk(paths.RUN_LOG, pos, first_tail=tail))
        elif route == "/api/core":
            self._send_json(self._core_payload())
        elif route.startswith("/api/export/"):
            self._export(route.rsplit("/", 1)[-1])
        else:
            self._send_error(404, "not found")

    def _status(self):
        running = lock.is_running()
        pid = lock.current_run_pid()
        state = lock.read_state()
        now = int(time.time())
        started = state.get("started_at") or 0
        cfg = config.load()
        cron_info = _cron_status()
        cores = core.all_core_info(cfg)
        active = cores["active"]
        running_core = state.get("core_type", "")
        if running and running_core in core.CORE_TYPES:
            active = running_core
        info = cores["cores"][active]
        phase = state.get("phase", "idle")
        if running and phase in ("", "idle", "done", "failed"):
            phase = "running"
        elif not running and phase in ("starting", "latency", "download", "commit", "stopping"):
            # The process died without writing a final phase (kill -9 / power loss).
            phase = "failed"
        return {
            "running": running,
            "pid": pid if running else 0,
            "mode": state.get("mode", ""),
            "phase": phase,
            "started_at": started if running else 0,
            "elapsed": (now - started) if running and started else 0,
            "stop_requested": bool(lock.stop_requested()) if running else False,
            "iterate": bool(cfg.get("iterate_enabled")),
            "node_count": len([n for n in cfg.get("nodes", []) if n.get("enabled", True)]),
            "cron": bool(cron_info.get("installed")),
            "cron_line": cron_info.get("line", ""),
            "core": info,
            "core_type": active,
            "cores": cores["cores"],
            "last": {
                "phase": state.get("phase", "idle"),
                "finished_at": state.get("finished_at", 0),
                "best_ip": state.get("best_ip", ""),
                "best_latency": state.get("best_latency", 0),
                "best_speed": state.get("best_speed", 0),
                "last_time": state.get("last_time", ""),
                "error": state.get("error", ""),
            },
            "version": __version__,
            "state_dir": str(paths.STATE_DIR),
            "time": now,
        }

    def _core_payload(self):
        info = core.all_core_info(config.load())
        info.update({
            "updating": _core_update["updating"],
            "updating_type": _core_update.get("type", ""),
            "message": _core_update["message"],
            "error": _core_update["error"],
            "finished_at": _core_update["finished_at"],
        })
        return info

    def _export(self, name):
        cfg = config.load()
        exports = cfg.get("export", {})
        if name == "log":
            self._serve_file(paths.RUN_LOG, "speedtest.log", cache=False)
        elif name == "result.csv":
            if not exports.get("csv", True):
                self._send_error(404, "CSV export is disabled")
                return
            self._serve_file(paths.RESULT_FILE, "result.csv", cache=False)
        elif name in ("result.json", "best.json"):
            if not exports.get("json", True):
                self._send_error(404, "JSON export is disabled")
                return
            target = paths.RESULT_JSON if name == "result.json" else paths.BEST_JSON
            rows, when = result.read_result()
            if not target.exists() or not rows:
                self._send_error(404, "no result yet")
                return
            self._serve_file(target, name, cache=False)
        else:
            self._send_error(404, "not found")

    # ── API: POST ──────────────────────────────────────────────────────
    def _api_post(self, route, body):
        if route == "/api/start":
            self._start(body)
        elif route == "/api/stop":
            self._stop()
        elif route == "/api/config":
            self._save_config(body)
        elif route == "/api/core/update":
            self._update_core(body)
        else:
            self._send_error(404, "not found")

    def _start(self, body):
        mode = body.get("mode", "start")
        if mode not in ("start", "retest"):
            self._send_error(400, "mode must be start or retest")
            return
        if lock.is_running():
            self._send_error(409, "已有测速在运行")
            return
        cfg = config.load()
        try:
            core.ensure_core(cfg)
        except core.CoreError as exc:
            self._send_error(400, str(exc))
            return
        enabled = [item for item in cfg.get("nodes", []) if item.get("enabled", True)]
        if not enabled:
            self._send_error(400, "没有启用任何节点，请先在「节点」页添加并启用节点")
            return
        active = core.active_type(cfg)
        compatible = 0
        for item in enabled:
            try:
                parsed = links.parse_link(item.get("link", ""))
                core.validate_proxy(parsed.proxy, active)
                compatible += 1
            except (links.LinkError, ValueError, core.CoreError):
                continue
        if not compatible:
            self._send_error(
                400, "没有与当前内核 %s 兼容的节点（xray 不支持 hysteria2 和带 plugin 的 SS），"
                     "请切换内核或修改节点" % active)
            return

        env = os.environ.copy()
        env["CFST_APP_DIR"] = str(paths.APP_DIR)
        env["CFST_STATE_DIR"] = str(paths.STATE_DIR)
        env["CFST_CONFIG_DIR"] = str(paths.CONFIG_DIR)
        env["CFST_CONFIG"] = str(paths.CONFIG_FILE)
        env["CFST_LOG_DIR"] = str(paths.LOG_DIR)
        env["PYTHONPATH"] = str(paths.APP_DIR) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        paths.SPAWN_LOG.parent.mkdir(parents=True, exist_ok=True)
        handle = open(paths.SPAWN_LOG, "ab", buffering=0)
        try:
            subprocess.Popen(
                [sys.executable, "-m", "cfspeedtest", "run", mode],
                cwd=str(paths.APP_DIR),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            self._send_error(500, "无法启动测速进程: %s" % exc)
            return
        finally:
            handle.close()
        self._send_json({"started": True, "mode": mode}, status=202)

    def _stop(self):
        if not lock.is_running():
            self._send_json({"stopped": True, "message": "当前没有运行中的测速"})
            return
        lock.request_stop()
        lock.write_state(stop_requested=True, phase="stopping")
        self._send_json({
            "stop_requested": True,
            "message": "已请求停止：各 worker 跑完当前 IP 即停，随后完成下载实测并导出结果",
        })

    def _save_config(self, body):
        cfg = body.get("config", body)
        if not isinstance(cfg, dict):
            self._send_error(400, "config must be an object")
            return
        normalized = config.normalize(cfg)
        warnings = _config_warnings(normalized)
        saved = config.save(normalized)
        cron_error = ""
        try:
            cron.apply(saved.get("schedule", {}))
        except cron.CronError as exc:
            cron_error = str(exc)
        _cron_cache["ts"] = 0
        self._send_json({
            "config": saved,
            "warnings": warnings,
            "cron_error": cron_error,
            "message": "配置已保存" + ("；定时任务: %s" % cron_error if cron_error else ""),
        })

    def _update_core(self, body):
        requested = str(body.get("type") or "").strip().lower()
        if requested and requested not in core.CORE_TYPES:
            self._send_error(400, "未知内核类型: %s" % requested)
            return
        core_type = requested or core.active_type(config.load())
        tag = str(body.get("tag") or "").strip()
        with _core_update_lock:
            if _core_update["updating"]:
                self._send_json({
                    "updating": True,
                    "updating_type": _core_update.get("type", ""),
                    "message": "已有内核正在更新，请稍候",
                })
                return
            _core_update.update({
                "updating": True,
                "type": core_type,
                "message": "正在下载 %s 内核%s..." % (
                    core_type, (" " + tag) if tag else "（最新版）"),
                "error": "",
                "finished_at": 0,
            })

        def worker():
            logger = Logger(paths.CORE_UPDATE_LOG, echo=False)
            try:
                info = core.update_core(core_type, tag=tag or None, log=logger.log)
                _core_update.update({
                    "updating": False,
                    "type": core_type,
                    "message": "%s 已更新到 %s" % (core_type, info.get("version", "")),
                    "error": "",
                    "finished_at": int(time.time()),
                })
            except Exception as exc:
                _core_update.update({
                    "updating": False,
                    "type": core_type,
                    "message": "%s 更新失败" % core_type,
                    "error": str(exc),
                    "finished_at": int(time.time()),
                })
                logger.log("内核更新失败: %s" % exc)

        threading.Thread(target=worker, name="core-update", daemon=True).start()
        self._send_json({
            "updating": True,
            "type": core_type,
            "message": "已开始更新 %s 内核" % core_type,
        }, status=202)


def serve(listen=None, port=None):
    paths.ensure_dirs()
    cfg = config.load()
    address = listen or cfg["web"]["listen"]
    number = int(port or cfg["web"]["port"])
    server = ThreadingHTTPServer((address, number), Handler)
    server.daemon_threads = True
    print("cf-speedtest web UI: http://%s:%d/ (Ctrl-C to stop)" % (address, number), flush=True)
    if not cfg["web"].get("token") and address not in ("127.0.0.1", "localhost", "::1"):
        print("警告: 未设置访问令牌且监听非回环地址，任何能访问该端口的人都能启动测速。",
              flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
