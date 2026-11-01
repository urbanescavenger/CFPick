#!/bin/sh
# Uninstall cf-speedtest.  By default the configuration, results and logs are
# kept; pass --purge to remove them as well.
set -eu

PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

APP_DIR=/opt/cf-speedtest
CONFIG_DIR=/etc/cf-speedtest
STATE_DIR=/var/lib/cf-speedtest
LOG_DIR=/var/log/cf-speedtest
UNIT=/etc/systemd/system/cf-speedtest-web.service

[ "$(id -u)" = 0 ] || { echo "请使用 root 运行" >&2; exit 1; }

if command -v cfst >/dev/null 2>&1; then
    cfst cron remove >/dev/null 2>&1 || true
fi

systemctl disable --now cf-speedtest-web.service >/dev/null 2>&1 || true
rm -f "$UNIT"
systemctl daemon-reload >/dev/null 2>&1 || true
rm -f /usr/local/bin/cfst

if [ "$PURGE" = 1 ]; then
    rm -rf "$APP_DIR" "$CONFIG_DIR" "$STATE_DIR" "$LOG_DIR"
    echo "已卸载并删除配置、结果与日志。"
else
    rm -rf "$APP_DIR"
    echo "已卸载程序；保留 $CONFIG_DIR、$STATE_DIR、$LOG_DIR（使用 --purge 一并删除）。"
fi
