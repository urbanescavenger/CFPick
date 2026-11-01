# cf-speedtest —— Debian / Ubuntu 独立版

这是 [`luci-app-passwall-speedtest`](../README.CN.md) 的 Debian/Ubuntu 独立实现，位于分支 `DB`。
它不再依赖 OpenWrt 与 PassWall，而是**自带代理内核模块**：目前提供 **mihomo** 与 **Xray-core**
两个可切换、可分别升级的内核，用节点分享链接拉起本地 SOCKS，把每个候选 Cloudflare IP 临时写进
内核配置，先做延迟初筛，再对最优候选做真实下载实测，最后把结果导出为 CSV/JSON，并提供一个
Python3 标准库实现的 Web 可视化页面。

> 与 OpenWrt 版的定位差异：OpenWrt 版会把最优 IP 写回 PassWall / hosts / MosDNS 等运行配置；
> Debian 版按需求**只导出结果**（`result.csv`、`result.json`、`best.json`），不修改系统
> hosts、DNS 或代理客户端配置，避免误改生产环境。

## 功能

* **可切换、可升级的内核模块**：内置 **mihomo**（MetaCubeX/mihomo）与 **Xray-core**
  （XTLS/Xray-core）两个模块，从 GitHub Releases 按架构下载，保存在
  `/var/lib/cf-speedtest/core/`。在 Web「内核」页选择当前使用的内核，并可分别安装/升级
  （支持指定版本标签），升级与应用本体解耦，互不影响；CLI 为
  `cfst update-core --type mihomo|xray|all`。
* **节点分享链接即 worker**：支持 `vless://`、`vmess://`、`trojan://`、`ss://`、
  `hysteria2://`（含 REALITY、WS、gRPC、HTTP/2、XHTTP、obfs、v2ray-plugin 等常见参数）。
  每个节点是一个并行 worker，链接里的服务器地址会被候选 CF IP 替换，端口保持不变。
  当前内核为 Xray 时，hysteria2 节点和带 plugin 的 SS 节点会被跳过（Xray-core 不支持），
  其余 vless/vmess/trojan/ss 会从同一份链接解析结果转换成 Xray JSON 出站配置。
  Xray 支持 `xhttp` 传输（vless/vmess/trojan）；mihomo 的 xhttp 目前仅覆盖 VLESS。
* **延迟初筛 + 多探测 fail-fast**：每个 IP 探测 N 次，任意一次失败立即丢弃；全部成功才保留，
  再按 `tl` / `tll` / `tlr` 阈值过滤（延迟上限默认不限，见下方配置表说明）。
* **真实下载实测**：所有 worker 停止探测后，逐节点串行测延迟最优的前 N 个 IP（默认 5，最多 10），
  用 curl `speed_download` 换算 MB/s；5 秒内不足 1 MB 的候选会被快速中止并判失败。
* **多 worker 调度**：并发上限可配；首个 worker 完成全部候选且取得有效结果时，其余 worker
  跑完当前 IP 即停（与 OpenWrt 版一致）。
* **限时迭代收敛**：每个节点独立循环，每遍只复测上一遍通过的 IP，直到时长结束或候选收敛到
  ≤ 下载候选数（关闭下载实测时为 3）。
* **复测现有最优**：`cfst run retest` 只使用当前 `result.csv` 中该节点的行与链接里的原始 IP，
  不重新下载在线列表。
* **候选 IP 来源**：内置 IPv4/IPv6 CIDR 列表（每个 /24 取样，可选扫描整个 /24）、在线 CM 源
  （`IP:PORT#国家码`，按五个列表分别过滤端口/国家）、自定义文件、复测模式。
* **Web 可视化**：状态 3 秒轮询、开始/停止/复测、按节点分组的最优 IP、完整结果表、
  历史延迟折线图（Chart.js 本地内置，带 tooltip/点击详情）、增量日志、内核管理。
* **结果导出**：`result.csv`、`result.json`、`best.json`；自动滚动保留 10 份 CSV，
  持久历史 `history.csv`（5000 行上限）。
* **定时任务**：保存配置时幂等写入 root crontab，只维护带 `cf-speedtest` 标记的块。
* **单实例锁**：定时重叠、页面连点、SSH 手敲同时触发时只跑一个；残留锁自动接管。
* **停止语义**：停止后各 worker 跑完当前 IP 即停，但仍会完成已通过 IP 的下载实测并导出结果。

## 环境要求

* Debian 11+ / Ubuntu 20.04+（Python 3.8+）
* `python3`（标准库即可，无第三方依赖）
* `curl`（延迟与下载探测）
* `cron`（可选，仅定时测速需要）
* 能访问 GitHub（下载 mihomo / Xray 内核）与你的节点

## 安装

### 一键部署（推荐）

在目标 Debian/Ubuntu 机器上执行：

```bash
curl -fsSL https://raw.githubusercontent.com/urbanescavenger/luci-app-passwall-speedtest/DB/debian/deploy.sh -o /tmp/cfst-deploy.sh
sudo bash /tmp/cfst-deploy.sh
rm -f /tmp/cfst-deploy.sh
```

或者从仓库运行：

```bash
git clone -b DB https://github.com/urbanescavenger/luci-app-passwall-speedtest.git
cd luci-app-passwall-speedtest
sudo bash debian/deploy.sh
```

`deploy.sh` 会：

1. 安装依赖（git / curl / ca-certificates / cron / python3）；
2. 把分支 `DB` 拉到 `/opt/cf-speedtest-src`（已存在则更新）；
3. 调用 `install.sh` 安装/更新到 `/opt/cf-speedtest`，保留已有配置；
4. 按需下载 mihomo / Xray 内核；
5. 重启 Web 服务并做 `/api/ping` 健康检查；
6. 打印 Web 地址、SSH 隧道命令、配置/结果/日志路径。

常用参数：

```bash
sudo bash debian/deploy.sh --core all
sudo bash debian/deploy.sh --listen 0.0.0.0 --token "$(openssl rand -hex 24)"
sudo bash debian/deploy.sh --core none          # 只升级程序，不动内核
sudo bash debian/deploy.sh --uninstall
sudo bash debian/deploy.sh --purge
```

默认安装/检查**当前配置使用的内核**（全新安装时是 mihomo，已安装时跳过）；
`--core all` 安装或升级两个内核，`--core xray` 单独安装 Xray。重新执行脚本即可升级程序，
已有 `/etc/cf-speedtest/config.json` 不会被覆盖。

> 推荐先下载到文件再执行，既方便审查，也避免脚本与交互式 apt 共用 stdin。
> 脚本已尽量禁用 apt/dpkg 的交互提示；如果你仍想用管道方式，脚本可以运行，
> 但文件方式是更稳妥的默认做法。

### 手动安装

```bash
git clone -b DB https://github.com/urbanescavenger/luci-app-passwall-speedtest.git
cd luci-app-passwall-speedtest
sudo sh debian/install.sh
```

安装脚本会：

1. 复制程序到 `/opt/cf-speedtest`（含 `uninstall.sh`）；
2. 创建 `/etc/cf-speedtest/config.json`（权限 600）、`/var/lib/cf-speedtest`、
   `/var/log/cf-speedtest`；
3. 安装/启用并重启 `cf-speedtest-web.service`（默认 `http://127.0.0.1:8787/`）；
   没有 systemd 的容器只打印手动启动命令；
4. 创建 `/usr/local/bin/cfst` 命令。

已有配置不会被覆盖。

### 升级

推荐直接用 deploy 脚本做“只更新程序、不动内核”：

```bash
curl -fsSL https://raw.githubusercontent.com/urbanescavenger/luci-app-passwall-speedtest/DB/debian/deploy.sh -o /tmp/cfst-deploy.sh
sudo bash /tmp/cfst-deploy.sh --core none
rm -f /tmp/cfst-deploy.sh
```

或者手动：

```bash
cd luci-app-passwall-speedtest
git pull
sudo sh debian/install.sh          # 会重启 Web 服务
```

内核在 Web「内核」页单独升级，或：

```bash
sudo cfst update-core --type mihomo
sudo cfst update-core --type xray
sudo cfst update-core --type all
```

### Web 在线更新程序

安装后，Web「内核」页底部有「程序更新」卡片，显示当前版本、代码提交、分支和源码目录。
点击「更新程序」会：

1. 从 `/opt/cf-speedtest-src` 拉取当前分支；
2. 重新安装到 `/opt/cf-speedtest`（保留配置）；
3. 重启 `cf-speedtest-web`，页面短暂断连后自动恢复。

要求：

- `/opt/cf-speedtest-src` 是 `deploy.sh` 创建的 git 仓库（手动 clone 安装时可把它放到该路径）；
- 系统使用 systemd（更新通过 `systemd-run` 在独立 cgroup 中执行，避免被 Web 重启杀掉）。

从**没有这个按钮的旧版本**第一次升级时，仍需在服务器执行一次上面的
`deploy.sh --core none`；之后的版本更新可以直接在 Web 里点按钮。

### 卸载

```bash
sudo /opt/cf-speedtest/uninstall.sh            # 保留配置、结果、日志
sudo /opt/cf-speedtest/uninstall.sh --purge    # 全部删除
```

也可以在仓库里运行 `sudo sh debian/uninstall.sh`。

## 首次使用

```bash
sudo cfst update-core                 # 安装当前内核（默认 mihomo）
sudo cfst update-core --type xray     # 需要 Xray 时再装
sudo cfst update-core --type all      # 两个都装
```

也可以打开 Web 页面 → **内核** → 分别点击 mihomo / Xray 卡片的「安装」，并选择当前使用的内核。

然后：

1. **节点** → 粘贴分享链接（每行一条，或逐条添加），保存；
   节点解析状态会显示 `vless · host:port` 或错误原因。
2. **IP 列表** → 选择候选来源。默认内置 IPv4；使用在线 CM 源时配置五个列表的国家码和端口。
3. **设置** → 调整延迟阈值、探测次数、下载实测、迭代、定时任务。
4. 点击「开始测速」。运行中可在「日志」页看逐 IP 进度；结束后「概览」刷新结果与图表。

### 内核选择

两个内核模块的差异：

| | mihomo | Xray-core |
| --- | --- | --- |
| 节点协议 | vless / vmess / trojan / ss / hysteria2 | vless / vmess / trojan / ss |
| 传输方式 | tcp / ws / grpc / h2 / http；xhttp（仅 VLESS） | tcp / ws / grpc / xhttp（Xray 26 已移除 h2/http 传输） |
| SS plugin（obfs / v2ray-plugin） | 支持 | 不支持（跳过） |
| 自签证书 / allowInsecure | 支持 | Xray 26.x 已移除 `allowInsecure`，自签证书节点请用 mihomo |
| REALITY / WS / gRPC | 支持 | 支持（WS/gRPC 在新版 Xray 中标记为 deprecated，但仍可用） |
| 内核升级 | 独立 | 独立 |

在 Web「内核」页切换并保存后，下一次测速生效；升级内核不会中断正在运行的测速
（进程持有旧二进制，下一次启动使用新版本）。每个内核卡片里的自定义路径优先于托管内核；
卡片上的「安装 / 升级」始终更新托管内核，不会覆盖自定义二进制。

## Web 页面

| 页签 | 内容 |
| --- | --- |
| 概览 | 运行状态、全局最优、内核版本、定时任务、按节点分组的最优 IP、历史趋势图、完整结果表、CSV/JSON 下载 |
| 节点 | 分享链接、名称、启用开关、每节点的 CM 列表指派、解析状态 |
| IP 列表 | 五个在线 CM 列表的启用/名称/国家码/端口 |
| 设置 | 候选来源、延迟与丢包阈值、探测参数、下载实测、限时迭代、定时任务、内核路径/DNS、Web 监听与访问令牌 |
| 日志 | 增量拉取运行日志，2 秒自动刷新，自动滚动，下载日志 |
| 内核 | 选择当前内核（mihomo / Xray），分别查看版本/路径/来源，按卡片安装或升级（可填版本标签），设置每个内核的自定义二进制路径；底部「程序更新」可在线拉取代码并重启 Web |

### 访问令牌

默认只监听 `127.0.0.1`，不设令牌。若要在局域网/公网访问：

1. 先在「设置」里设置访问令牌；
2. 重启 Web 服务：`systemctl restart cf-speedtest-web`；
3. 建议用 Nginx/Caddy 反向代理并加 TLS，不要直接暴露明文端口。

令牌通过 `X-CFST-Token` 请求头传递；页面会保存在浏览器 `localStorage`。
下载链接使用 `?token=` 查询参数。

## 命令行

```bash
cfst run start          # 完整一轮：下载候选 → 延迟初筛 → 下载实测 → 导出
cfst run retest         # 复测现有 result.csv 中的候选，不下载在线列表
cfst run replace        # 仅重新导出当前结果（CSV/JSON）
cfst status             # JSON：运行状态、阶段、最优 IP、内核版本、定时任务
cfst config             # 打印当前配置
cfst nodes              # 列出节点并校验链接
cfst cores              # 列出两个内核模块的安装状态与版本
cfst update-core                      # 升级当前内核
cfst update-core --type xray          # 单独升级 Xray
cfst update-core --type all           # 两个都升级
cfst update-core --type mihomo --tag v1.19.33   # 指定版本
cfst cron apply|remove  # 按当前配置写入/移除 crontab
cfst serve              # 前台启动 Web（--listen 0.0.0.0 --port 8787）
```

`cfst` 是 `python3 -m cfspeedtest` 的包装脚本，安装后可直接使用；
在源码目录里也可以 `PYTHONPATH=. python3 -m cfspeedtest status`。

## 配置说明

配置文件：`/etc/cf-speedtest/config.json`（JSON，权限 600）。

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `ip_source` | `builtin_ipv4` | `builtin_ipv4` / `builtin_ipv6` / `online` / `custom_file` |
| `ip_online_url` | CM 源 | 在线源地址，格式 `IP:PORT#CC` |
| `custom_ip_file` | 空 | 自定义列表路径，支持 CIDR 与纯 IP |
| `custom_allip` | `false` | 自定义 IPv4 CIDR 是否展开 /24 内全部地址 |
| `ip_lists` | 5 行 | 在线 CM 源的五个过滤列表：`enabled` / `name` / `regions` / `port` |
| `latency_max` | `0`（不限） | 平均延迟上限（ms），0 = 不限。延迟包含节点自身 RTT，远端节点常 >200ms，不要照搬直连阈值 |
| `latency_min` | `40` | 平均延迟下限（ms），0 = 不限 |
| `loss_max` | `0.2` | 丢包率上限（0–1） |
| `probe_url` | Google 204 | 经节点 SOCKS 做 HTTP HEAD 的 URL |
| `test_count` | `30` | 每个节点最多测试的候选数 |
| `probe_timeout` | `5` | 单次 curl `--max-time`（秒） |
| `probes` | `3` | 每个 IP 的探测次数（1–5，全部成功才保留） |
| `max_workers` | `5` | 并发 worker 上限；0 = 全部（迭代模式忽略此值，全部同时运行） |
| `download_enabled` | `true` | 是否做真实下载实测 |
| `download_count` | `5` | 每节点下载候选数（1–10） |
| `download_url` | CF 10 MB | 下载实测 URL |
| `download_time` | `10` | 单 IP 下载时限（秒），截断部分仍按已下载字节算平均速度 |
| `iterate_enabled` | `false` | 限时迭代 |
| `iterate_minutes` | `30` | 迭代时长（分钟） |
| `nodes` | `[]` | `{name, link, ip_list, enabled}` 数组 |
| `core.type` | `mihomo` | 当前使用的内核模块：`mihomo` / `xray`（节点兼容性见上表） |
| `core.paths.mihomo` | 空 | 自定义 mihomo 二进制路径；空 = 使用托管内核 |
| `core.paths.xray` | 空 | 自定义 Xray 二进制路径；空 = 使用托管内核 |
| `core.dns_nameserver` | 空 | 内核 DNS；空 = 系统 DNS |
| `schedule` | 关闭 | `enabled` / `custom_enabled` / `custom_cron` / `hour` |
| `web.listen` / `web.port` | `127.0.0.1:8787` | Web 监听；修改后需重启服务 |
| `web.token` | 空 | API 访问令牌；空 = 不校验 |
| `export.csv` / `export.json` | `true` | 是否提供对应格式的下载（CSV 仍会写入内部结果文件） |

## 结果文件

| 路径 | 内容 |
| --- | --- |
| `/var/lib/cf-speedtest/result.csv` | 当前结果；表头 `IP 地址,已发送,已接收,丢包率,平均延迟,下载速度(MB/s),地区码,节点`，末尾 `# Speed test time:` |
| `/var/lib/cf-speedtest/result.csv.1` … `.9` | 最近 10 次结果滚动 |
| `/var/lib/cf-speedtest/result.json` | 本次结果的结构化导出（`generated_at` / `best` / `nodes` / `rows` 全量） |
| `/var/lib/cf-speedtest/best.json` | 精简的最优导出（`generated_at` / `best` / 各节点最优 `nodes`，不含全量 rows） |
| `/var/lib/cf-speedtest/history.csv` | 持久历史（每块 = 一次运行中各节点最优，最多 5000 行） |
| `/var/lib/cf-speedtest/last.log` | 最近一次完整运行日志 |
| `/var/log/cf-speedtest/speedtest.log` | 运行日志；每次运行开始时滚动为 `.1`…`.5` |
| `/var/lib/cf-speedtest/core/mihomo` / `core/xray` | 两个托管内核二进制（可分别升级） |
| `/var/lib/cf-speedtest/core/mihomo.version` / `xray.version` | 当前安装的版本标签 |
| `/var/log/cf-speedtest/mihomo.log` / `xray.log` | 内核输出（排查节点握手/证书问题） |
| `/var/log/cf-speedtest/core-update.log` | 内核下载/升级日志 |
| `/var/log/cf-speedtest/update-app.log` | Web「程序更新」的 git/install 输出 |
| `/var/log/cf-speedtest/spawn.log` | Web 启动测速子进程时的早期输出 |

下载接口：`/api/export/result.csv`、`/api/export/result.json`、`/api/export/log`
（设置令牌后需带 `?token=...`）。

## 定时任务

在「设置 → 定时任务」中启用后保存，会写入 root crontab，例如：

```cron
# >>> cf-speedtest >>>
0 */3 * * * /usr/local/bin/cfst run start >/dev/null 2>&1
# <<< cf-speedtest <<<
```

自定义 cron 为五段表达式；注意分钟字段不要写 `*`（`* 19 * * 4` 表示周四 19 点内每分钟一次）。
命令行方式：`cfst cron apply` / `cfst cron remove`。

## 与 OpenWrt 版的对应关系

| OpenWrt 版 | Debian 版 |
| --- | --- |
| PassWall 节点 `address` 改写 + `app.sh run_socks` | 生成临时 mihomo YAML / Xray JSON 配置，替换服务器地址，拉起私有 SOCKS 端口 |
| 稳定节点 / 全局节点切换 | 不需要：内核进程与系统代理隔离，不影响实流量 |
| 写回 PassWall / hosts / MosDNS / 阿里云 DDNS | 只导出 CSV/JSON（按需求） |
| LuCI 页面 + rpcd/ucode | Python3 标准库 HTTP 服务 + 原生 JS |
| procd + uci 配置 | systemd + JSON 配置 |
| `/tmp` 结果 + `/etc/config/...log` | `/var/lib/cf-speedtest` + `/var/log/cf-speedtest` |
| cron | crontab（root） |

## 排查

* **内核未安装 / 下载失败**：`cfst update-core --type mihomo|xray|all`；也可以手动放置二进制，
  在 Web「内核」页对应卡片里填写自定义路径。架构不支持时会在更新日志里提示。
  `cfst cores` 可查看两个模块的安装状态。
* **节点链接解析失败**：`cfst nodes` 查看错误；目前支持 vless/vmess/trojan/ss/hysteria2。
  SSR、TUIC、SOCKS 节点暂不支持（它们不能通过替换服务器地址来测 CF IP，或参数未覆盖）。
* **切到 xray 后部分节点被跳过**：Xray-core 不支持 hysteria2、带 plugin 的 SS 节点，
  以及 Xray 26 已移除的 h2/http 传输；引擎会记录“与当前内核不兼容，跳过”，改用 mihomo 即可。
* **节点是 VMess/Trojan + xhttp**：用 Xray 内核；mihomo 目前只支持 VLESS 的 xhttp，
  对其它协议的 xhttp 节点会提示改用 Xray。
* **xray 节点握手失败并提示证书**：Xray 26.x 移除了 `allowInsecure`，自签证书节点请改用
  mihomo，或给节点换有效证书。
* **探测全部失败**：看 `/var/log/cf-speedtest/mihomo.log` 或 `xray.log`；常见原因是节点端口/协议参数错误、
  证书 SNI 不匹配、节点本身不可用，或探测 URL 经该节点不可达。
* **下载实测全部失败**：确认 `download_url` 经该节点可达；失败时保留延迟排序结果，不会丢数据。
* **想临时改路径/端口**：所有路径支持环境变量：
  `CFST_APP_DIR`、`CFST_CONFIG`、`CFST_CONFIG_DIR`、`CFST_STATE_DIR`、`CFST_LOG_DIR`。
* **看服务日志**：`journalctl -u cf-speedtest-web -f`。

## 开发与测试

```bash
cd debian
PYTHONPATH=. python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 -m cfspeedtest --help
```

本地运行 Web（不安装）：

```bash
cd debian
export CFST_STATE_DIR=$PWD/.dev/state CFST_CONFIG_DIR=$PWD/.dev/etc CFST_LOG_DIR=$PWD/.dev/log
export CFST_SKIP_CRON=1      # 开发时不要改动本机 crontab
PYTHONPATH=. python3 -m cfspeedtest serve --port 8787
```

`.dev/` 已随仓库忽略或可自行删除；不要把它提交到仓库。
