"""Cloudflare IP speed test for Debian/Ubuntu.

Standalone port of luci-app-passwall-speedtest.  It manages its own proxy
core modules (mihomo and Xray-core, independently selectable and upgradable),
screens candidate Cloudflare IPs by latency through each configured node,
optionally measures real download throughput, and exposes a small web UI plus
CSV/JSON export.
"""

__version__ = "1.0.0"
