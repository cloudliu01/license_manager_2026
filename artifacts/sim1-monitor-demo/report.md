# SIM1 旁路监控实测（2026-09-27 13:20 -04:00）

**结论：通过。** 独立监控进程按实际 PID/监听端口附着，抓取 SIM1 TCP 内容并写入本地 SQLite；自造 SIM1 协议**不代表**真实 FlexNet 报文可解码。

| 角色 | 实际 PID | TCP 端口 |
|---|---:|---:|
| lmgrd | 422578 | 48779 |
| vend_a | 422584 | 48273 |
| vend_b | 422587 | 36811 |
| 独立监控进程（root/CAP_NET_RAW） | 422593 | 监听 lo 抓包 |

进程在生成报告时仍运行；当前 PID/端口也保存在 [run.json](run.json)。[capture.sqlite](capture.sqlite) 是实时增长的数据库；[license.dat](license.dat) 和 [lmgrd.log](lmgrd.log) 可供交叉核对。

## 实测数据

- `listeners`：三个监听端口分别对应上表中的不同真实 PID；不是从模拟器引擎伪造的 PID。
- `tcp_segments`：**16** 条原始 TCP payload 段；`frames`：**16** 条重组后的原始 SIM1 binary frame（含 BLOB `raw_bytes` 与 hex `raw_hex`）及解码 JSON。`raw_hex <> lower(hex(raw_bytes))` **0** 条，解码错误 **0** 条。
- `license_events`：**4** 条，均由实际抓到的请求和应答关联，`correlation=MATCHED_SIM1_REQUEST`：

| daemon | feature | user | status | 预期 |
|---|---|---|---|---|
| vend_a | alpha | alice | GRANTED | OUT，alpha 占 1 |
| vend_a | alpha | bob | DENIED | 拒绝，不增加占用 |
| vend_b | beta | carol | GRANTED | OUT，beta 占 1 |
| vend_a | alpha | NULL | RETURNED | IN，alpha 归零 |

`RETURNED` 的请求只携带 checkout_id，不包含用户名，因此事件表的 user 保持 **NULL**，而非臆造；可通过 checkout_id 与之前已捕获的 GRANTED 关联。另有心跳帧，但**没有心跳席位事件**。日志有 OUT×2、DENIED×1、IN×1；实时快照为 `alpha total=1, in_use=0, denied=1`、`beta total=2, in_use=1, denied=0`，两次 OUT 减一次 IN 与总在用 1 一致。

```bash
sqlite3 artifacts/sim1-monitor-demo/capture.sqlite \
  "SELECT pid,daemon,port FROM listeners ORDER BY port;"
sqlite3 artifacts/sim1-monitor-demo/capture.sqlite \
  "SELECT feature,client_user,status,correlation FROM license_events ORDER BY id;"
sqlite3 artifacts/sim1-monitor-demo/capture.sqlite \
  "SELECT id,opcode,decoded_json,raw_hex,hex(raw_bytes) FROM frames ORDER BY id LIMIT 3;"
```

## 重现与停止

```bash
/opt/miniforge3/envs/venv312/bin/python tools/sim1_monitor_demo.py --stop
/opt/miniforge3/envs/venv312/bin/python tools/sim1_monitor_demo.py
```

需要 Linux `lo`/IPv4 和无交互 sudo（或 `CAP_NET_RAW`）。监控只可读取 **attach 后** 的流量；丢包、跨包 IP 分片、IPv6、真实 vendor 私有载荷、历史席位及生产级权限治理仍未解决。缺失帧时不能从流量推断精确使用量；日志与 lmstat 是独立对账来源。原始数据含 dummy 用户/主机名，应限制数据库访问。
