"""Idempotent crontab management.

Only the block between the two markers is owned by this application; every
other crontab line is preserved byte-for-byte.
"""

import os
import shutil
import subprocess
import sys

BEGIN = "# >>> cf-speedtest >>>"
END = "# <<< cf-speedtest <<<"


def _disabled():
    """Dev/test switch: never touch the real crontab."""
    return os.environ.get("CFST_SKIP_CRON") == "1"


class CronError(RuntimeError):
    pass


def cli_command():
    configured = os.environ.get("CFST_BIN", "")
    if configured:
        return configured
    installed = "/usr/local/bin/cfst"
    if os.access(installed, os.X_OK):
        return installed
    # Development fallback: an absolute Python invocation.
    return "%s -m cfspeedtest" % shlex_quote(sys.executable)


def shlex_quote(value):
    if not value or any(ch in value for ch in " \t'\""):
        return "'" + value.replace("'", "'\\''") + "'"
    return value


def build_line(settings):
    if settings.get("custom_enabled"):
        expression = settings.get("custom_cron", "0 3 * * *").strip()
    else:
        hour = int(settings.get("hour", 24) or 24)
        expression = "0 */%d * * *" % hour
    return "%s %s run start >/dev/null 2>&1" % (expression, cli_command())


def _read_crontab():
    if _disabled():
        return ""
    executable = shutil.which("crontab")
    if not executable:
        raise CronError("未安装 crontab（apt install cron）")
    completed = subprocess.run([executable, "-l"], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=15)
    if completed.returncode not in (0, 1):
        raise CronError("读取 crontab 失败（crontab -l 返回 %d）" % completed.returncode)
    return completed.stdout.decode("utf-8", "replace")


def _write_crontab(text):
    if _disabled():
        return
    executable = shutil.which("crontab")
    if not executable:
        raise CronError("未安装 crontab（apt install cron）")
    completed = subprocess.run([executable, "-"], input=text.encode("utf-8"),
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               timeout=15)
    if completed.returncode != 0:
        raise CronError("写入 crontab 失败: %s" %
                        completed.stderr.decode("utf-8", "replace").strip())


def _strip_block(text):
    kept = []
    inside = False
    for line in text.splitlines():
        if line.strip() == BEGIN:
            inside = True
            continue
        if line.strip() == END:
            inside = False
            continue
        if not inside:
            kept.append(line)
    return kept


def apply(settings):
    """Install/remove the managed block.  Returns (enabled, line)."""
    lines = _strip_block(_read_crontab())
    if settings.get("enabled"):
        line = build_line(settings)
        lines.extend(["", BEGIN, line, END])
    else:
        line = ""
        while lines and not lines[-1].strip():
            lines.pop()
    text = "\n".join(lines) + ("\n" if lines else "")
    _write_crontab(text)
    return bool(settings.get("enabled")), line


def current():
    try:
        lines = _read_crontab().splitlines()
    except CronError:
        return {"installed": False, "line": ""}
    inside = False
    found = ""
    for line in lines:
        if line.strip() == BEGIN:
            inside = True
            continue
        if line.strip() == END:
            inside = False
            continue
        if inside and line.strip() and not found:
            found = line.strip()
    return {"installed": bool(found), "line": found}
