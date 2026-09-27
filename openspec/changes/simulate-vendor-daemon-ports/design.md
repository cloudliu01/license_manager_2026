## Context

参见 `proposal.md` 与 [截图证据表](evidence.md)。当前 `lmgrd/cli.py` 以 `config.port + 1000 + idx` 编造端口/PID，实际上只有一个 manager Uvicorn HTTP listener；`SimulatorService` 和进程内 SQLite 在同一进程记账。要让宿主机监控程序验证真实的 PID→socket→连接关联，**不能只把同一进程的多个 socket 伪装成子 PID**。

官方参考：[Revenera FlexNet Publisher License Administration Guide（Synopsys 官方镜像）](https://www.synopsys.com/content/dam/synopsys/support/documents/licensing/enduser.pdf) 第 4 章 VENDOR Lines 与第 10 章 lmgrd（启动并维护 vendor daemon、转介请求）；[Synopsys 实例](https://www.synopsys.com/support/licensing-installation-computeplatforms/licensing.html) 的 vendor daemon 端口日志。官方资料支持进程与连接职责，但未提供所附现场截图的私有报文字节定义。

## Goals / Non-Goals

**Goals:** 每个 daemon 为真实独立子进程/PID及其 TCP listener；manager 监管、发现和汇总，worker 各自负责真实记账；观测流程按截图可证实的 0→4 阶段执行；为监控程序测试提供进程/端口/会话与 log/lmstat 对账基准。

**Non-Goals:** 在缺少原始样本时宣称逐字节兼容真实 FlexNet、伪造不可见的字段/加密载荷、加载厂商二进制、三机冗余、生产监控 agent 或生产级认证；首版不做 daemon 自动重启后的在用席位恢复。

## Decisions

1. **证据分层和格式门槛。** 截图只包含现场摘要，而不是双向 PCAP；已证实的字段、值、字节偏移及其适用范围见 `evidence.md`。一例 147 B A 类请求中可见 user/host/vendor，一例 37 B B 类发现响应在偏移 28..30 可见大端端口；C 类示例存在头、分片和无法解码的 payload。此前计划中的固定 `LMS1`/TLV **不是截图格式，取消其作为对外协议规范**。实施分两条路径：先按截图验证连接拓扑、独立 PID、发现和阶段顺序；**完整字节格式阶段设 BLOCKED**，收到合法脱敏 PCAP/hex + 事件标注后再冻结逐字段协议和 golden bytes。若没有样本但需跑端到端业务测试，只能另行明确批准一套标记为“模拟专用”的报文，不能声称严格 follow 真实字节格式。截图记录的 16 次 enquiry、~119 s 心跳、50/46 B 疑似归还均为个例，不能升格成通用固定次数/长度/时钟。
2. **配置及端口。** 延续已起草的自定义语法 `PORT <manager-port>`、`DAEMON <name> [PORT <1..65535>]` 和 `FEATURE ... [DAEMON <name>]`；未配置 daemon 端口时在 40000..50000（含）随机次序直接 bind，不能先检测再释放。顶层 manager 固定，拒绝端口冲突/重复定义/未知归属/`PORT 0`，支持隐式 `default`。这个指定范围是**模拟器约束**而非真实 FlexNet 必然的动态端口范围。所有 socket 在 manager 预绑定并保留，再通过 POSIX FD 继承交给子进程；只有子进程报告成功持有并监听，manager 才报告就绪。
3. **真正分离进程及状态所有权。** Linux 主路径：manager 通过 `subprocess` 派生每个 dummy daemon 子进程（传递受控配置与预绑定 FD），真实 parent PID 为 manager、child PID 各异；每个子进程拥有该 vendor 的 `SimulatorService`/独立内存 SQLite 配额/去重/队列，不能在子进程之间共享 SQLite 连接。manager 只持有 daemon→PID/端口/feature 配置索引；其 lmstat 状态、checkout/queue 查询通过有界的本机 IPC 向各子进程取实时快照并聚合，不从过期缓存编造 0。manager 按 checkout_id 查询归属时可向 worker 发只读查找，未知时返回错误。worker 日志经专用 IPC 交由 manager **单写入者**顺序写入标准 FlexLM debug log，包含实际 PID/端口，防止多进程交错损坏；业务 OUT/IN/DENIED 的作者仍是 worker。保留 core 的业务规则与锁，校验 daemon 归属及按 daemon 隔离的 request_id 去重。相比全局状态留在 manager 的替代方案，真实 vendor 进程承担记账更接近目标模型，但要增加 IPC、超时与汇总失败处理。
4. **进程生命周期。** 全部子进程经 IPC 报告监听就绪后开放 manager enquiry，日志才写 ready；任何启动失败均终止/回收全部子进程并释放所有 FD。SIGTERM/SIGINT 时 manager 先停止新请求，再给 workers 发送停机命令、等待、超时后强制回收并 flush 日志；子进程通过控制 IPC 监测 parent EOF，以避免 manager 意外退出留孤儿。运行中 worker 意外退出时 manager 标记该 daemon unavailable（不能再返回可用端口或成功的状态/checkout），并输出故障事件；**不自动重启并清零使用量**，因为缺少跨进程持久化状态。重新启动整个模拟器后席位恢复初始配置（与已有 in-memory 设计一致），文档明确限制。
5. **manager/daemon 公共连接职责。** manager 接收连接，按 feature 或 checkout_id 找 worker 的实际端口，只读汇总；worker 只接收其 feature 的 CHECKOUT/CHECKIN/HEARTBEAT。manager 不代理业务消息，错误 daemon 返回错误。客户端先向 manager 发 enquiry、取得端口，再直接到 worker 建立持久 TCP 连接，发送 checkout、周期性模拟心跳、显式 checkin 后结束；同一连接可有多条请求并处理半包/粘包/超时。模拟心跳只证明连接活着，断线/FIN 不自动归还。**以上约束仅定义行为，不冻结未知 wire payload**；取得原始字节前 TCP 请求/响应的逐字节格式由证据门槛限制。
6. **审计测试和工具迁移。** `lmstat` 经 manager 只读汇总，保持 `-a/-f/-i` 输出；workload、exporter 验证、Docker seed 改用批准的 TCP 客户端，Docker 固定发布 manager 和 vendor 端口，移除旧 HTTP 路径。Linux 集成测试读取 parent/child PID、`/proc` socket 与监听地址，比对日志与 enquiry，再用各 worker 的测试真值、标准 debug log、`lmstat -a` 快照对账。TCP 元数据只能证明端点和时序；心跳、FIN、TCP 重传不算 license 事务。A/B/C 已知字段的格式测试只核对有证据的片段，未知载荷保持未知。日志缺失、同用户并发、采样竞态或 worker 中断时标记未知/待核对并用新快照重建基线，而不是伪装成完全实时且准确。

## Risks / Trade-offs

- [截图不含原始字节] → `evidence.md` 限定可证实的片段；没有 PCAP 时 **BLOCKED** 逐字节兼容验收，也不将 `LMS1` 当作截图复刻。
- [独立进程的状态、日志和 pid 生命周期复杂] → 每 vendor 单独状态、manager 单写日志、受控 IPC、原子启动/回收及异常降级；测试 kill worker、manager 信号及 PID/端口释放。
- [真实许可用量不等于网络流量] → 以 lmstat 快照确认当前用量，以 log 解释变化；无法辨识或丢数据时承认不确定性。
- [动态端口、NAT/权限] → 静态 Docker 端口，生产部署需开放真实 daemon 端口；`/proc` 检查仅 Linux 测试，采集权限由未来 agent 规划。
- [协议更改一次性 BREAKING] → 仓库内所有调用者统一迁移；未知二进制格式不靠修改真实工具兼容性来掩盖。

## Migration Plan

1. 先核对截图证据、获取脱敏原始捕获与同一次 debug log/lmstat 以冻结 wire 验收；若拿不到，仍可实施进程和连接拓扑，但**严格报文格式阶段暂停**。
2. 改造 parser、端口 FD 传递和每 daemon 独立进程/状态/日志 IPC，完成失败与异常进程清理测试。
3. 在证据充分或另行批准模拟专用报文之后完成 TCP 客户端、enquiry/业务链路、lmstat/workload/Docker/验证脚本迁移；按截图阶段和可证实字段建立回归样本。
4. 审计夹具验证 PID/端口/连接、日志与快照对账，运行全套测试；整体回滚 CLI/客户端和 Docker 配置，避免半迁移。
