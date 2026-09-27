## Why

当前模拟器只在 `lmgrd` 的 HTTP 端口监听，日志却声称 vendor daemon 另有端口；客户端直接向 manager 发送 HTTP/JSON checkout，与希望验证的“启动 daemon → 询问 lmgrd → 直连 daemon”连接过程不符。未来运行在 license server 主机上的审计程序需要用 PID/端口识别服务、关联网络连接，并以 debug log 与 lmstat 对账。`samples/pictures/IMG_3695.jpg` 至 `IMG_3698.jpg` 展示了连接过程的抓包分析，但也明确指出业务载荷不可解码，不能据此复刻真实 FlexNet 报文或只凭流量还原准确用量。

## What Changes

- dummy license 中用 `DAEMON <name> [PORT <1..65535>]` 为每个 daemon 指定固定端口；不写 `PORT` 时，从 **40000–50000（含端点）** 随机尝试绑定未占用 TCP 端口。`PORT 0` 不作为动态端口的别名。
- 启动 `lmgrd` 时为显式声明及隐式 `default` daemon 启动**独立子进程、独立 PID 和 TCP listener**；全部成功后才对外报告就绪，日志写入各自真实 PID/端口。失败时整体退出并释放子进程与端口。
- 客户端通过 manager 的 TCP enquiry 查询 daemon/feature 对应的端口，再向 daemon 的 TCP 连接发送 checkout、checkin/return；manager 保留状态和 lmstat 所需的只读查询。
- **BREAKING**：模拟器内 HTTP/JSON 管理与业务 API 改为 TCP 通信；仓库内 workload、lmstat、exporter 验证脚本、Docker 种子脚本、测试及文档同步迁移。传输流程按截图中可证实的 A/B/C 类型、enquiry、daemon 通话、心跳与释放时序设计；**逐字节格式的实施以原始脱敏 PCAP/hex 样本为前置条件**，不凭截图补猜未知字段。
- 每个 daemon 子进程拥有其 feature 的状态与事务，manager 负责进程监管、发现及汇总；日志、错误路由和生命周期可测试。
- 为将来的审计程序提供可验证的模拟环境：测试按 manager PID→监听端口→daemon 端口→TCP 会话识别拓扑，把 OUT/IN/DENIED 日志与 lmstat 快照和真实席位状态对账；明确哪些字段只能从模拟协议解码、哪些在真实 FlexNet 流量里无法保证获取。

## Capabilities

### New Capabilities

- `simulator-vendor-daemon-transport`: dummy 端口配置和分配、独立子进程启动/停止、lmgrd TCP enquiry、daemon TCP 事务、协议证据门槛，以及面向审计测试的可观测性与对账基准。

### Modified Capabilities

无（仓库尚无 OpenSpec 主规格；现有 `specs/` 属于另一套规划文档）。

## Impact

影响 `simulators/src/license_manager_simulators/{core,lmgrd,lmstat,workload}`、`simulators/tests`、`tools/flexlm_exporter/verify_exporter.py`、`docker/simulator/`、`docker/docker-compose.yml`、`tests/tools/`、示例 license 与使用文档。原有 HTTP/JSON 客户端需要一起升级；仍保留 `lmstat` 文本输出及供 exporter 使用的 lmutil 包装器。

此协议仅模拟双阶段 TCP 连接和许可业务语义，**不实现、不宣称兼容真实 FlexNet wire protocol 或厂商客户端**；子进程为项目自写 dummy daemon，而非真实 vendor 可执行文件。缺少原始报文时无法验证严格字节兼容；未来生产审计器的真实协议解码与部署权限不在本变更实施范围内。
