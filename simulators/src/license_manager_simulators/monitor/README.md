# SIM1 旁路监控程序

本目录提供一个**独立于模拟器的 Linux 测试监控程序**：根据真实 `lmgrd` PID 自动发现 dummy vendor daemon 子进程及其监听端口，旁路抓取 TCP，重组并解码本项目的 **SIM1** 报文，将原始二进制、hex 和解码 JSON 写入本地 SQLite。它**不能解码真实 FlexNet/厂商协议**，也不通过模拟器内部状态伪造抓包数据。

## 启动与 attach

要求：Linux、Python ≥3.11、可读取目标进程的 `/proc` 信息，以及抓包权限（root 或 `CAP_NET_RAW`）。以下命令从**仓库根目录**运行。请用 dummy license 和测试用户；抓包可能包含用户/主机标识。

先准备 `/tmp/license.dat`（dummy license 格式与示例见[模拟器手册](../../../../docs/manual-simulator.md)）。终端 A：启动模拟器并记录 `lmgrd` PID（wrapper 使用 `exec`，所以 `$!` 是实际 Python manager PID）：

```bash
PYTHON=/opt/miniforge3/envs/venv312/bin/python \
  simulators/wrappers/lmgrd -c /tmp/license.dat -l /tmp/lmgrd.log &
LMGRD_PID=$!
echo "lmgrd PID=$LMGRD_PID"
ps --ppid "$LMGRD_PID" -o pid,ppid,cmd
```

终端 B：将实际 PID 填入 `--pid`，**先启动监控，再产生 checkout 流量**：

```bash
cd /home/cloud/Github_personal/license_manager_2026
mkdir -p /tmp/sim1-audit
sudo env PYTHONPATH="$PWD/simulators/src" \
  /opt/miniforge3/envs/venv312/bin/python \
  -m license_manager_simulators.monitor.cli \
  --pid <实际lmgrd_PID> \
  --iface lo \
  --db /tmp/sim1-audit/capture.sqlite \
  --ready-file /tmp/sim1-audit/ready
```

将 `<实际lmgrd_PID>` 换成终端 A 输出的数字，不要原样复制尖括号。`--ready-file` 可选；文件出现后才开始测试请求。`lo` 用于本机 loopback IPv4 流量；从其他机器连入时，改成服务器上承载该连接的网卡（例如 `eth0`）。daemon PID **不用逐个传入**：监控从 `/proc/<lmgrd_pid>/task/<pid>/children` 和各进程的 socket FD/inode 映射 TCP LISTEN 端口。必须在相同的 PID/network 可见范围内运行；容器与宿主机的 namespace 隔离可能导致发现/抓包失败。

若已通过 `pip install -e simulators` 安装，可用 `sudo ... sim-monitor --pid ... --db ...`，但仍须确保 root 使用的是安装了本项目的 Python；上述 `PYTHONPATH` 命令更明确。没有 sudo/raw socket 权限时程序会报错，不会拿日志或 `lmstat` 输出冒充原始网络流量。

## SQLite 数据

监控会创建以下表（运行中使用 SQLite WAL；需要一致备份时先停止监控或使用 SQLite backup API）：

| 表 | 内容 |
|---|---|
| `listeners` | 发现时间、manager PID、真实监听 PID、daemon 名、端口、socket inode |
| `tcp_segments` | 抓到的 TCP **payload** 分段：方向、端点、seq、`payload_bytes` BLOB、`payload_hex`；不是包含 IP/TCP 头的完整网络包 |
| `frames` | TCP 流重组后的完整 SIM1 **应用层帧**：`raw_bytes` BLOB、`raw_hex`、opcode、方向、PID/端口、`decoded_json`、`decode_status` |
| `license_events` | 可关联的 SIM1 checkout/checkin 应答：feature、user/host（请求可见时）、checkout_id、quantity、GRANTED/DENIED/RETURNED 等状态、原因、请求与响应的 frame ID、关联标记 |

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

`license_events` 仅记录**观测到并能对应的 SIM1 应答**，不代表完整历史或权威当前用量；心跳不产生许可事件。checkin 请求只含 checkout_id 时，`client_user` 保持 `NULL`，不能凭空填写。若监控中途 attach、缺包、无法关联请求，`correlation` 会标示 `MISSING_REQUEST`，不能把缺失数据当成 0；需结合 `lmstat` 当前快照和 debug log 的 OUT/IN/DENIED 对账。`frames` 只存完整、可识别边界的 SIM1 帧；未组成完整帧的 payload 仍保留在 `tcp_segments` 中。

## 一键复现与验证

仓库提供可重复的演示脚本：

```bash
/opt/miniforge3/envs/venv312/bin/python tools/sim1_monitor_demo.py
# 运行结束后模拟器和监控仍在后台：
sqlite3 artifacts/sim1-monitor-demo/capture.sqlite \
  'SELECT feature,client_user,status FROM license_events ORDER BY id;'
/opt/miniforge3/envs/venv312/bin/python tools/sim1_monitor_demo.py --stop
```

脚本产生 alpha/beta 的 GRANTED×2、DENIED×1、RETURNED×1 和心跳，验证真实 PID/端口、原始 hex/BLOB 一致性、日志及最终席位快照；参阅 [`artifacts/sim1-monitor-demo/report.md`](../../../../artifacts/sim1-monitor-demo/report.md)。带实际 raw socket 的自动化测试可在具有无交互 sudo 的机器上执行：

```bash
RUN_RAW_CAPTURE_TEST=1 conda run -n venv312 pytest -q \
  simulators/tests/integration/test_monitor_live.py
```

## 限制与停止

- 当前只解析所选接口的 **IPv4/TCP SIM1**，不支持真实 FlexNet 私有/加密载荷、IPv6、IP 分片、抓包前已发生的流量或丢包后的完整历史重建。生产监控 agent 与权限治理不在此测试工具范围内。
- 默认本机 loopback，原始 SQLite 中包含 dummy 用户、主机及报文字节。妥善限制文件访问；演示产物中的 SQLite/run.json 已加入 `.gitignore`，不要提交生产抓包。
- 前台运行时 `Ctrl-C` 停止监控；后台一键演示用 `tools/sim1_monitor_demo.py --stop`。请勿让两个监控实例同时写同一个 SQLite 文件。
