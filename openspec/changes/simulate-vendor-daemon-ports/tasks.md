## 1. 证据门槛与配置

- [ ] 1.1 根据 `evidence.md` 建立可追溯的 0–4 阶段/已知字段/未知字段表；核对 147 B A 请求、37 B B 响应中偏移 28..30 的大端端口、C 类头/分片、心跳及疑似释放的截图文字；证据表经人工审阅通过。
- [ ] 1.2 **真实 FlexNet 格式 BLOCKED**。取得经授权脱敏的双向 PCAP/hex、同一次操作标注和 debug log/lmstat；完成 TCP 重组与不同用户/feature 的真实 golden-byte 测试。用户已批准单独的模拟专用 SIM1 hex；这些生成向量不能关闭本项。
- [x] 1.3 扩展 `LicenseConfig`/parser 支持显式与隐式 default daemon、固定/动态端口和整文件归属验证；单测覆盖 `PORT 0`、重复、冲突、未知归属及 FEATURE/DAEMON 顺序。
- [x] 1.4 实现 manager 固定端口及 40000..50000（含）随机直接 bind、保持 FD 到子进程接管；单测验证忙端口跳过、范围约束和失败后的 FD 释放（使用可注入候选集合）。

## 2. 独立进程、状态和日志

- [x] 2.1 将 daemon 移为 manager 派生的独立子进程，每个 child 继承一个预绑定 TCP socket、拥有唯一 PID；Linux 集成测试使用 `/proc`/socket 信息核对真实 parent PID、child PID、端口和启动日志一致。
- [ ] 2.2 各 daemon 实例只持有自身 feature 的 SQLite store/配额/队列和去重；core 单测验证跨 daemon 的 checkout_id/request_id 不会误路由或超卖。（已实现各 worker 独立 store/事务；仍需跨 daemon 重试测试。）
- [ ] 2.3 增加受控本机 IPC：worker readiness、状态/明细快照、checkout_id 查找、日志事件；manager 作为单一 FlexLM debug log 写入者；测试多 worker 并发 OUT/IN/DENIED 行无交错且 lmstat 汇总正确。（IPC 和单写入者已实现，仍需并发审计断言。）
- [ ] 2.4 实现原子启动、信号停机、父进程断开后的子进程退出及运行中 worker 崩溃降级（不自动清零重启）；端到端测试 PID/FD 全释放、残余 worker 不存在、死 worker 的在用量不误报为 0。

## 3. 截图阶段与已批准的模拟专用 SIM1 TCP 业务（真实 wire 另由 1.2 限制）

- [ ] 3.1 将证据支持的 manager enquiry 和返回 daemon 端口、客户端直连 daemon 的阶段顺序实现为 TCP 交互；抓取测试流量确认两个不同目的端口、方向及独立服务 PID，验证 TCP 分片/粘包正确处理。没有 PCAP 不做逐字节兼容断言。（流程、端口和分片/粘包测试通过；仍需外部抓包回归。）
- [x] 3.2 实现 daemon checkout、显式 checkin、持续但不改变席位的模拟 HEARTBEAT、连接关闭不自动归还；结合 log 和 lmstat 测试状态变更及多报文/长连接，不把截图中的心跳周期/释放长度当成所有厂商常量。
- [ ] 3.3 模拟协议自生成 hex、拆包/粘包及长度/UTF-8 错误的单测已加入；真实 A/B/C 的原始 golden bytes 仍依赖 1.2、不能由 SIM1 测试代替。补充多用户/feature golden vectors 和端到端抓包边界测试。

## 4. 工具迁移、监测和回归

- [ ] 4.1 在已批准协议上迁移 `lmstat` 只读查询、workload 的 enquiry/checkout/checkin、exporter 验证和 Docker seed；集成测试验证 `lmstat -a/-f/-i` 的文本输出与 exporter 指标接口不退化。（代码与 Docker seed 验证已通过；本环境无 Go，真实 exporter 二进制验证仍待运行。）
- [x] 4.2 更新 Docker 的固定 vendor 端口映射、示例 license 和用户文档；文档核对 PID/端口关系，说明动态范围是模拟器约束、独立子进程的异常状态及不能直接运行真实厂商客户端。
- [x] 4.3 增加 Linux 旁路审计工具：由真实 parent/child PID 与 socket inode 发现端口，以 AF_PACKET 抓指定 interface 的 IPv4 TCP，去重/重组 SIM1；SQLite 分表保留 TCP segment、frame 原始 BLOB/hex、解码 JSON 及可关联 license_events，并联同 OUT/IN/DENIED、状态快照对账。已提供 Linux root/CAP_NET_RAW 环境下 `RUN_RAW_CAPTURE_TEST=1` 的自动化抓包集成测试和实测报告。
- [ ] 4.4 对账用例注入日志缺口、同用户并发、worker 崩溃、抓包中途启动/丢包及快照竞态；用 UNKNOWN/待核对标记缺失证据而不推断精确用量，通过集成测试验证。
- [ ] 4.5 完成旧 HTTP 路由退出与全部集成测试迁移后，运行 `conda run -n venv312 pytest -q`，可用时运行 `ruff check .`；验收报告分别标出“拓扑与阶段通过”和“真实字节格式通过/仍 BLOCKED”。（HTTP CLI/路由已移除；63 tests passed；新文件 Ruff 通过，全仓库 Ruff 仍有历史告警。）
