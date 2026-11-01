"""Configuration file handling.

The config is a single JSON document (default /etc/cf-speedtest/config.json).
It is deliberately plain JSON so it can be edited by hand as well as from the
web UI.  :func:`normalize` fills defaults and clamps values; unknown keys are
preserved so a newer UI writing extra fields does not lose them.
"""

import copy
import json
import os
import re
import tempfile
from pathlib import Path

from . import paths

REGION_CODES = [
    "JP", "SG", "KR", "HK", "TW", "TH", "VN", "ID", "PH", "MY",
    "IN", "KH", "DE", "NL", "FR", "GB", "FI", "SE", "CH", "RU",
    "TR", "UA", "US", "CA", "BR", "AU", "AE", "ZA",
]

DEFAULT_CONFIG = {
    "ip_source": "builtin_ipv4",          # builtin_ipv4 | builtin_ipv6 | online | custom_file
    "ip_online_url": "https://zip.cm.edu.kg/all.txt",
    "custom_ip_file": "",
    "custom_allip": False,
    "ip_lists": [
        {"enabled": True, "name": "JP/SG/KR", "regions": ["JP", "SG", "KR"], "port": 443},
        {"enabled": False, "name": "", "regions": [], "port": 443},
        {"enabled": False, "name": "", "regions": [], "port": 443},
        {"enabled": False, "name": "", "regions": [], "port": 443},
        {"enabled": False, "name": "", "regions": [], "port": 443},
    ],
    # 延迟是 curl 经内核 SOCKS 测到的全链路 time_pretransfer，天然包含节点
    # 自身 RTT；远端节点常常 >200ms，默认卡上限会把所有候选全部丢弃，故默认不限。
    "latency_max": 0,
    "latency_min": 40,
    "loss_max": 0.2,
    "probe_url": "https://www.google.com/generate_204",
    "test_count": 30,
    "probe_timeout": 5,
    "probes": 3,
    "max_workers": 5,
    "download_enabled": True,
    "download_count": 5,
    "download_url": "https://speed.cloudflare.com/__down?bytes=10000000",
    "download_time": 10,
    "iterate_enabled": False,
    "iterate_minutes": 30,
    "nodes": [],
    "core": {
        "type": "mihomo",
        "paths": {"mihomo": "", "xray": ""},
        "dns_nameserver": "",
    },
    "schedule": {
        "enabled": False,
        "custom_enabled": False,
        "custom_cron": "0 3 * * *",
        "hour": 24,
    },
    "web": {
        "listen": "127.0.0.1",
        "port": 8787,
        "token": "",
    },
    "export": {
        "csv": True,
        "json": True,
    },
}


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
    return default


def _as_int(value, default, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and number < minimum:
        number = minimum
    if maximum is not None and number > maximum:
        number = maximum
    return number


def _as_float(value, default, minimum=None, maximum=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and number < minimum:
        number = minimum
    if maximum is not None and number > maximum:
        number = maximum
    return number


def _clean_text(value, default=""):
    if value is None:
        return default
    return str(value).strip()


def _clean_name(value, fallback):
    name = _clean_text(value)
    name = re.sub(r"[\r\n,]+", " ", name)
    return name or fallback


def _normalize_regions(value):
    if isinstance(value, str):
        tokens = re.split(r"[\s,]+", value)
    elif isinstance(value, (list, tuple)):
        tokens = []
        for item in value:
            tokens.extend(re.split(r"[\s,]+", str(item)))
    else:
        tokens = []
    out = []
    for token in tokens:
        code = token.strip().upper()
        if code and code not in out:
            out.append(code)
    return out


def _normalize_ip_lists(value):
    source = value if isinstance(value, list) else []
    out = []
    for index in range(5):
        item = source[index] if index < len(source) and isinstance(source[index], dict) else {}
        out.append({
            "enabled": _as_bool(item.get("enabled"), index == 0),
            "name": _clean_text(item.get("name")),
            "regions": _normalize_regions(item.get("regions")),
            "port": _as_int(item.get("port"), 443, 1, 65535),
        })
    return out


def _normalize_nodes(value):
    source = value if isinstance(value, list) else []
    out = []
    for index, item in enumerate(source):
        if not isinstance(item, dict):
            continue
        link = _clean_text(item.get("link"))
        if not link:
            continue
        out.append({
            "name": _clean_name(item.get("name"), "node%d" % (index + 1)),
            "link": link,
            "ip_list": _clean_text(item.get("ip_list")),
            "enabled": _as_bool(item.get("enabled"), True),
        })
    # make names unique; duplicate names would merge two workers' results
    seen = {}
    for node in out:
        base = node["name"]
        count = seen.get(base, 0)
        if count:
            node["name"] = "%s-%d" % (base, count + 1)
        seen[base] = count + 1
    return out


def _valid_cron(expr):
    parts = expr.split()
    if len(parts) != 5:
        return False
    return all(re.match(r"^[0-9A-Za-z*/,?-]+$", part) for part in parts)


def normalize(data):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if isinstance(data, dict):
        for key, value in data.items():
            if key not in ("ip_lists", "nodes", "core", "schedule", "web", "export"):
                cfg[key] = value

    cfg["ip_source"] = _clean_text(cfg.get("ip_source"), "builtin_ipv4")
    if cfg["ip_source"] not in ("builtin_ipv4", "builtin_ipv6", "online", "custom_file"):
        cfg["ip_source"] = "builtin_ipv4"
    cfg["ip_online_url"] = _clean_text(cfg.get("ip_online_url"), DEFAULT_CONFIG["ip_online_url"])
    cfg["custom_ip_file"] = _clean_text(cfg.get("custom_ip_file"))
    cfg["custom_allip"] = _as_bool(cfg.get("custom_allip"), False)

    cfg["ip_lists"] = _normalize_ip_lists(data.get("ip_lists") if isinstance(data, dict) else None)
    cfg["latency_max"] = _as_int(cfg.get("latency_max"), 0, 0, 60000)
    cfg["latency_min"] = _as_int(cfg.get("latency_min"), 40, 0, 60000)
    cfg["loss_max"] = _as_float(cfg.get("loss_max"), 0.2, 0.0, 1.0)
    cfg["probe_url"] = _clean_text(cfg.get("probe_url"), DEFAULT_CONFIG["probe_url"])
    cfg["test_count"] = _as_int(cfg.get("test_count"), 30, 1, 100000)
    cfg["probe_timeout"] = _as_int(cfg.get("probe_timeout"), 5, 1, 120)
    cfg["probes"] = _as_int(cfg.get("probes"), 3, 1, 5)
    cfg["max_workers"] = _as_int(cfg.get("max_workers"), 5, 0, 128)
    cfg["download_enabled"] = _as_bool(cfg.get("download_enabled"), True)
    cfg["download_count"] = _as_int(cfg.get("download_count"), 5, 1, 10)
    cfg["download_url"] = _clean_text(cfg.get("download_url"), DEFAULT_CONFIG["download_url"])
    cfg["download_time"] = _as_int(cfg.get("download_time"), 10, 1, 60)
    cfg["iterate_enabled"] = _as_bool(cfg.get("iterate_enabled"), False)
    cfg["iterate_minutes"] = _as_int(cfg.get("iterate_minutes"), 30, 1, 10080)

    cfg["nodes"] = _normalize_nodes(data.get("nodes") if isinstance(data, dict) else None)

    core = data.get("core") if isinstance(data, dict) and isinstance(data.get("core"), dict) else {}
    core_type = _clean_text(core.get("type"), "mihomo").lower()
    if core_type not in ("mihomo", "xray"):
        core_type = "mihomo"
    configured_paths = core.get("paths") if isinstance(core.get("paths"), dict) else {}
    # ``path`` was the single-core field in the first iteration of this branch;
    # migrate it to the selected core's per-module path.
    legacy_path = _clean_text(core.get("path"))
    cfg["core"] = {
        "type": core_type,
        "paths": {
            "mihomo": _clean_text(configured_paths.get("mihomo"))
            or (legacy_path if core_type == "mihomo" else ""),
            "xray": _clean_text(configured_paths.get("xray"))
            or (legacy_path if core_type == "xray" else ""),
        },
        "dns_nameserver": _clean_text(core.get("dns_nameserver")),
    }

    schedule = data.get("schedule") if isinstance(data, dict) and isinstance(data.get("schedule"), dict) else {}
    custom_cron = _clean_text(schedule.get("custom_cron"), DEFAULT_CONFIG["schedule"]["custom_cron"])
    if not _valid_cron(custom_cron):
        custom_cron = DEFAULT_CONFIG["schedule"]["custom_cron"]
    cfg["schedule"] = {
        "enabled": _as_bool(schedule.get("enabled"), False),
        "custom_enabled": _as_bool(schedule.get("custom_enabled"), False),
        "custom_cron": custom_cron,
        "hour": _as_int(schedule.get("hour"), 24, 1, 24),
    }

    web = data.get("web") if isinstance(data, dict) and isinstance(data.get("web"), dict) else {}
    cfg["web"] = {
        "listen": _clean_text(web.get("listen"), "127.0.0.1") or "127.0.0.1",
        "port": _as_int(web.get("port"), 8787, 1, 65535),
        "token": _clean_text(web.get("token")),
    }

    export = data.get("export") if isinstance(data, dict) and isinstance(data.get("export"), dict) else {}
    cfg["export"] = {
        "csv": _as_bool(export.get("csv"), True),
        "json": _as_bool(export.get("json"), True),
    }

    return cfg


def load(create=True):
    path = paths.CONFIG_FILE
    data = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            data = {}
    cfg = normalize(data)
    if create and not path.exists():
        try:
            save(cfg)
        except OSError:
            pass
    return cfg


def save(cfg):
    cfg = normalize(cfg)
    path = Path(paths.CONFIG_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".config.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cfg, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return cfg
