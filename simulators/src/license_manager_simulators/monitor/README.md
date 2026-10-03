# SIM1 旁路监控程序

本目录提供一个**独立于模拟器的 Linux 测试监控程序**：根据真实 `lmgrd` PID 自动发现 vendor daemon 子进程及其监听端口，旁路抓取 TCP，重组并解码应用层帧，将原始二进制、hex 和解码 JSON 写入本地 SQLite。它原先只解码本项目的 **SIM1** 报文；对真实 FlexNet/厂商守护进程（lmgrd/vendor00 等，在 node0 上验证）会自动识别 **LSF-style broker 分帧**（0x2f magic + BE16 声明长度 + 类型/时间戳 + 字符串收割，可能看到 feature 名、user@host、tty、席位数）、**EDA 147 字节问候消息**和 **lmgrd ping**，并尽力解码。模拟器自身（`lmgrd/native.py`）也实现了同一原生风格状态面，因此对模拟器抓包可同时验证 SIM1 与 FlexLM 两条解码路径。它不通过模拟器内部状态伪造抓包数据。

## 启动与 attach

要求：Linux、Python ≥3.11、可读取目标进程的 `/proc` 信息，以及抓包权限（root 或 `CAP_NET_RAW`）。以下命令从**仓库根目录**运行（将 `/path/to/license_manager_2026` 换成实际路径，并使用已安装依赖的 Python）。`node0`、`vendor00` 为脱敏占位名。请用 dummy license 和测试用户；抓包可能包含用户/主机标识。

先准备 `/tmp/license.dat`（dummy license 格式与示例见[模拟器手册](../../../../docs/manual-simulator.md)）。终端 A：启动模拟器并记录 `lmgrd` PID（wrapper 使用 `exec`，所以 `$!` 是实际 Python manager PID）：

```bash
PYTHON="$(command -v python)" \
  simulators/wrappers/lmgrd -c /tmp/license.dat -l /tmp/lmgrd.log &
LMGRD_PID=$!
echo "lmgrd PID=$LMGRD_PID"
ps --ppid "$LMGRD_PID" -o pid,ppid,cmd
```

终端 B：将实际 PID 填入 `--pid`，**先启动监控，再产生 checkout 流量**：

```bash
cd /path/to/license_manager_2026
mkdir -p /tmp/sim1-audit
sudo env PYTHONPATH="$PWD/simulators/src" \
  "$(command -v python)" \
  -m license_manager_simulators.monitor.cli \
  --pid <实际lmgrd_PID> \
  --iface lo \
  --db /tmp/sim1-audit/capture.sqlite \
  --ready-file /tmp/sim1-audit/ready
```

将 `<实际lmgrd_PID>` 换成终端 A 输出的数字，不要原样复制尖括号。`--ready-file` 可选；文件出现后才开始测试请求。`lo` 用于本机 loopback IPv4 流量；从其他机器连入时，改成服务器上承载该连接的网卡（例如 `eth0`）。daemon PID **不用逐个传入**：监控从 `/proc/<lmgrd_pid>/task/<pid>/children` 和各进程的 socket FD/inode 映射 TCP LISTEN 端口。必须在相同的 PID/network 可见范围内运行；容器与宿主机的 namespace 隔离可能导致发现/抓包失败。

若已通过 `pip install -e simulators` 安装，可用 `sudo ... sim-monitor --pid ... --db ...`，但仍须确保 root 使用的是安装了本项目的 Python；上述 `PYTHONPATH` 命令更明确。没有 sudo/raw socket 权限时程序会报错，不会拿日志或 `lmstat` 输出冒充原始网络流量。

抓包 socket 自动附加**内核态 BPF 过滤器**（`SO_ATTACH_FILTER`，随端口发现每 0.5s 原子更新）：只有与已发现 license 端口相关的 IPv4/TCP 分段会进入用户态，网卡上的其余流量（NFS、UDP 等）不再占用接收队列。此前在 qa-ls 的 ens1f0 上无过滤抓包时内核丢包率约 58%，附加过滤器后丢包为 0（`capture_stats` 表每 5s 采样 packets/drops 可验证）。

**自查询通道（`--self-query`）**：监控主循环每 `SELF_QUERY_INTERVAL_S`（30s）自己 spawn 一次 `/usr/local/bin/lmutil lmstat -c <lmgrd端口>@127.0.0.1 -a -i`（可用环境变量 `LM_MONITOR_LMUTIL` 换成其他等价命令），并**专门在 `lo` 上开第二个抓包 socket** 捕获它的回环流量—对任意本机 IP 的连接 Linux 一律走 loopback，ens1f0 上看不到。detail/summary（`poller_details`/`poller_summaries` 及席位事件）由此来自我们自己的已确认查询，**不再依赖外部 poller** 的风险。此时 `--iface` socket 上的**外部 poller 查询流被整体丢弃**（qstream 标记后连续缓冲不进），只剩真实客户端 checkout 流；`LM_MONITOR_LMUTIL` 不可用时静默跳过该轮，等下一个 30s 周期，不做重试。不带 `--self-query` 且 `--iface lo` 时，查询流仍按 `--filter-queries` 语义标记并记录（供单机/集成测试）。

**多服务单实例**：`--pid` 可重复（如 `--pid 39007 --pid 65432`），一个监控进程同时监测同一台主机上的多个 lmgrd 树；每棵树独立 `discover()`（各自找到 vendor daemon 子进程与端口），端口→listener 映射合并（TCP 端口只属一棵树，按端口即按服务归属），BPF 合并端口表，`--self-query` 为**每个服务**各 spawn 一次 lmstat（用各自的 lmgrd 端口）。`frames`/`listeners` 的 `manager_pid` 列按各 listener 所属树盖章；`license_events`/`poller_*` 的 `server_pid`/`server_port` 本来就来自所在连接的 listener，天然按服务区分。任一服务的 lmgrd 进程消失会使监控退出（与单服务行为一致）。

**动态发现（`--discovery auto`）**：默认 `manual` 模式保持原语义—只盯 `--pid` 列出的树，任一棵消失即退出。`--discovery auto` 把树集合变成动态的：每个刷新周期（0.5s）里扫 `/proc` 里 argv0 以 `lmgrd` 开头的进程，**收集**新树（若它已有监听端口才收，刚 fork 还没 bind 的下一轮再试）、**淘汰**消失的树（记 `[monitor] tree ... dropped` 日志、在途 self-query dump 还既有回滚路径进 `self_query_errors`），monitor 只在收到信号时退出—lmgrd 重启（新 pid）自动完成“淘汰旧+收养新”，无需重启 monitor。`--pid` 在 auto 模式作为**额外钉住的树**（如 argv0 是 python 的 simulator），同样适用淘汰语义；树集合为空时 BPF 拒绝一切，空闲无害。进程扫描按 argv0 basename 前缀匹配（兼容 `lmgrd11.18` 这类带版本后缀的二进制），vendor daemon 与 python 进程不会误配。

**自查询超时（`--lmstat-timeout`，默认 5s）**：dump 是 all-or-nothing—超过时限的 lmstat 被 kill，其**已写入的部分行按服务回滚删除**（poller_summaries/poller_details/license_definitions/license_events 的 IN_USE 座位，按 `observed_at >= dump 开始` 且 `server_port IN 该服务的端口` 界定；checkout attempts 走 `--iface` 通道，永不回滚）；失败记录进 `self_query_errors`（observed_at/manager_pid/mgr_port/elapsed_s/reason，含回滚行数，spawn 失败也记在这里）。注意：慢站点（如三机冗余的 Cadence，单次 dump 20s）在 5s 默认值下每轮都会超时回滚—需要该服务的数据就调大时限或把 lmstat 指向可达的 master。

## SQLite 数据

监控会创建以下表（运行中使用 SQLite WAL；需要一致备份时先停止监控或使用 SQLite backup API）：

| 表 | 内容 |
|---|---|
| `listeners` | 发现时间、manager PID、真实监听 PID、daemon 名、端口、socket inode |
| `tcp_segments` | 抓到的 TCP **payload** 分段：方向、端点、seq、`payload_bytes` BLOB、`payload_hex`；不是包含 IP/TCP 头的完整网络包 |
| `frames` | TCP 流重组后可识别边界的应用层帧（SIM1、LSF-style broker 或 EDA 问候/ping）：`raw_bytes` BLOB、`raw_hex`、opcode、方向、PID/端口、`decoded_json`、`decode_status` |
| `license_events` | 可关联的 SIM1 checkout/checkin 应答，以及从真实 FlexLM 流量提取的观测（`FLEXLM_IN_USE`/`FLEXLM_CHECKOUT_ATTEMPT`/`FLEXLM_LICENSE_LOOKUP`/`FLEXLM_LICENSE_LINE`）：feature（可来自 ts-join 的 attempt 集合，多个用逗号分隔）、user/host/pid（可见时）、quantity、状态、原因、请求与响应的 frame ID、关联标记、checkout_id/checkout_ts |
| `poller_summaries` | 0x4e poller 席位汇总（poller 视角的 feature 总量）：`in_use`/`issued`/`report_ts`、`request_frame_id`、`correlation`、`poller_user`/`poller_pid`（来自 poller 自己的 greeting）。**每个 feature 只保留最近 120 次 observation** |
| `poller_details` | 0x14 poller 逐座位明细，**一行 = lmstat 一行用户记录**：`client_user`/`client_host`/`client_tty`/`client_version`、`checkout_id`、`checkout_ts`、`client_pid`/`correlation`（ts-join 归属）、`poller_user`/`poller_pid`；只含有真实 checkout 的 feature（无座位无行）。**每个 feature 只保留最近 120 次 observation**（`observation` 时间戳标识一次 dump） |
| `license_definitions` | `lmstat -i` 的 license 文件文本**在 wire 上是原始 payload（非 LSF 帧）**，逐行解析 INCREMENT/FEATURE：`keyword`/`feature`/`vendor`（行内 vendor daemon 名）/`version`/`expiry`/`seats`/`line`（整行）。跨 TCP 段的行按会话缓冲拼接。**每个 feature 保留最近 120 行** |

示例查询：

```bash
sqlite3 /tmp/sim1-audit/capture.sqlite \
  'SELECT pid,daemon,port FROM listeners ORDER BY port;'
sqlite3 /tmp/sim1-audit/capture.sqlite \
  'SELECT id,daemon,feature,client_user,status,reason,correlation FROM license_events ORDER BY id;'
sqlite3 /tmp/sim1-audit/capture.sqlite \
  'SELECT id,direction,opcode,decoded_json,raw_hex,hex(raw_bytes) FROM frames ORDER BY id LIMIT 10;'
sqlite3 /tmp/sim1-audit/capture.sqlite \
  'SELECT count(*) FROM frames WHERE raw_hex <> lower(hex(raw_bytes));'
```

`license_events` 仅记录**观测到并能对应的应答**，不代表完整历史或权威当前用量；心跳不产生许可事件。checkin 请求只含 checkout_id 时，`client_user` 保持 `NULL`，不能凭空填写。若监控中途 attach、缺包、无法关联请求，`correlation` 会标示 `MISSING_REQUEST`，不能把缺失数据当成 0；需结合 `lmstat` 当前快照和 debug log 的 OUT/IN/DENIED 对账。`frames` 只存完整、可识别边界的帧（SIM1 帧、LSF-style broker 帧、EDA 问候/ping 整条消息）；未组成完整帧的 payload 仍保留在 `tcp_segments` 中。FlexLM 帧的 `decode_status` 为 `FLEXLM_DECODED`，`decoded_json` 含 `proto`（`lsf-broker`/`eda-greeting`/`lmgrd-ping`）、方向及按帧类型提升的命名字段：0x3c 的 `feature`/`feature_handle`、0x4e 的 `in_use`/`issued`/`report_ts`（三数字布局，已与 `lmstat` 输出校准；退化变体只给不定名的 `counts`）、0x14 的 `user`/`host`/`tty`/`version`、0x02/0x08 的 `user`/`host`/`daemon`/`tty`（/`command`/`arch`）、0x13 的 `vendor_port`、问候的 `user`/`host`/`daemon`/`tty`/`pid`/`platform`；字段随帧格式而异。

FlexLM 侧的 `license_events` 由同流上下文生成：0x3c 特性查询（明文名或十六进制句柄）给后续 0x4e 席位汇总（写入 `poller_summaries`）与 0x14 用户行标注 `feature`（`MATCHED_FLEXLM_QUERY`；无前置查询为 `NO_FLEXLM_QUERY`）；0x14 席位行的 pid/feature 优先走 wire-native ts-join（座位 start epoch == 0x3d 客户端时间戳），命中时 `client_pid` 与 `feature` 都可能是逗号分隔的集合（同秒多进程 checkout）；两端时钟不同步时按同（user, host）±3s 容差回补（`MATCHED_CHECKOUT_TS_SKEW`/`AMBIGUOUS_CHECKOUT_TS_SKEW`）；checkout 与其座位必属同一主机，跨主机 attempt 永不 join）；仍零命中则回退最近 greeting holder（`HOLDER_NO_TS_MATCH`）或保持 NULL（`NO_CHECKOUT_MATCH`）；问候消息记录的身份（user/host）与 0x61 加密会话握手关联为 `FLEXLM_CHECKOUT_ATTEMPT`（`IDENTITY_FROM_GREETING`）—会话载荷加密，身份不明的会话不造事件。0x47 license lookup（C->S，checkout 前的条款查询）与 0x46 license line（S->C，daemon 回以 INCREMENT 明文行）同样记入 `license_events` 以保留完整帧观测；0x46 行的 `quantity` 恒为 NULL—INCREMENT 行里明示的是**池子大小**而非 checkout 数量（真实 checkout 无 count 即默认 1，见 0x14 的 `FLEXLM_IN_USE`），原始行文（含 seats）在 `reason`/`decoded_json`，条款主档在 `license_definitions`。

## 一键复现与验证

仓库提供可重复的演示脚本：

```bash
python tools/sim1_monitor_demo.py
# 运行结束后自动停止模拟器和监控；数据库仍可查询：
sqlite3 artifacts/sim1-monitor-demo/capture.sqlite \
  'SELECT feature,client_user,status FROM license_events ORDER BY id;'
# 若要保留服务用于调试：
python tools/sim1_monitor_demo.py --keep-running
python tools/sim1_monitor_demo.py --stop
```

脚本产生 alpha/beta 的 GRANTED×2、DENIED×1、RETURNED×1 和心跳，验证真实 PID/端口、原始 hex/BLOB 一致性、日志及最终席位快照；参阅 [`artifacts/sim1-monitor-demo/report.md`](../../../../artifacts/sim1-monitor-demo/report.md)。带实际 raw socket 的自动化测试可在具有无交互 sudo 的机器上执行：

```bash
RUN_RAW_CAPTURE_TEST=1 python -m pytest -q \
  simulators/tests/integration/test_monitor_live.py
```

## 限制与停止

- 当前只解析所选接口的 **IPv4/TCP** 流量，不支持 IPv6（lmgrd 常以 tcp6 双栈监听，客户端走 IPv4 连接时可正常抓取；`::1` 连接抓不到）、IP 分片、抓包前已发生的流量或丢包后的完整历史重建。
- SIM1 帧之外，真实 FlexNet 私有/加密载荷只做**启发式解码**（LSF-style broker 分帧 + 字符串收割）：字符串内容（feature、user@host、席位）可能可见；二进制字段不解释；未组成完整帧的 payload 仍保留在 `tcp_segments` 中，可用改进后的解码器对旧数据重放。`license_events` 仍只记录 SIM1 checkout/checkin 应答，FlexLM 帧不参与事件关联。
- 真实 FlexLM 服务器 fork 出的 vendor daemon 与 lmgrd **共享持有监听 socket**：`listeners` 表中共享端口归属记录为 manager PID（先发现者），daemon 名在子进程独占端口时才可见。
- 默认本机 loopback，原始 SQLite 中包含真实用户、主机及报文字节，妥善限制文件访问。抓真实服务器时建议在**回环接口**（`lo`）或专门指定的业务网卡上运行；繁忙服务器上的 `--iface` 全量抓包没有内核 BPF 过滤，会消耗较多 CPU。演示产物中的 SQLite/run.json 已加入 `.gitignore`，不要提交生产抓包。
- 前台运行时 `Ctrl-C` 停止监控；一键演示默认自动停止服务，仅 `--keep-running` 会保留后台进程（用 `tools/sim1_monitor_demo.py --stop` 结束）。请勿让两个监控实例同时写同一个 SQLite 文件。
