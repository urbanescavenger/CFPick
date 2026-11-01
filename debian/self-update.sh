#!/bin/sh
# Pull the current branch, re-install, and restart the web service.
# Invoked by the web UI through systemd-run so the restart of
# cf-speedtest-web does not kill this update process.
set -eu

SRC_DIR="${1:-/opt/cf-speedtest-src}"
BRANCH="${2:-DB}"
STATUS_FILE="${3:-/var/lib/cf-speedtest/update-app.json}"
LOG_FILE="${4:-/var/log/cf-speedtest/update-app.log}"

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$STATUS_FILE")"
if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE" 2>/dev/null || echo 0)" -gt 5242880 ]; then
    mv -f "$LOG_FILE" "$LOG_FILE.1"
fi
exec >>"$LOG_FILE" 2>&1

write_state() {
    STATE_UPDATING="$1" STATE_OK="$2" STATE_MESSAGE="$3" STATE_COMMIT="$4" \
    python3 - "$STATUS_FILE" <<'PY'
import json
import os
import sys
import tempfile
import time

path = sys.argv[1]
data = {
    "updating": os.environ.get("STATE_UPDATING") == "1",
    "ok": os.environ.get("STATE_OK") == "1",
    "message": os.environ.get("STATE_MESSAGE", ""),
    "commit": os.environ.get("STATE_COMMIT", ""),
    "updated_at": int(time.time()),
}
directory = os.path.dirname(path) or "."
os.makedirs(directory, exist_ok=True)
fd, tmp = tempfile.mkstemp(prefix=".update.", dir=directory)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(data, handle, ensure_ascii=False)
    handle.write("\n")
os.chmod(tmp, 0o644)
os.replace(tmp, path)
PY
}

echo "=== $(date '+%Y-%m-%d %H:%M:%S') update start: branch=$BRANCH src=$SRC_DIR"
write_state 1 0 "正在拉取代码..." ""

# Give the HTTP response that started this unit time to leave the web server.
sleep 1

trap 'write_state 0 0 "更新失败，请查看 $LOG_FILE" ""; exit 1' ERR
trap 'write_state 0 0 "更新被中断，请查看 $LOG_FILE" ""; exit 1' INT TERM

cd "$SRC_DIR"
export GIT_TERMINAL_PROMPT=0
git fetch --depth 1 origin "$BRANCH" </dev/null
git checkout -B "$BRANCH" FETCH_HEAD </dev/null
COMMIT="$(git rev-parse --short HEAD)"
echo "=== source now at $COMMIT"
write_state 1 0 "正在安装 $COMMIT..." "$COMMIT"

sh debian/install.sh </dev/null

write_state 0 1 "更新完成" "$COMMIT"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') update done: $COMMIT"
