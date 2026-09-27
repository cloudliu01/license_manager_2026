## Purpose

定义模拟器 dummy license 的 daemon 端口分配、自动启动、lmgrd TCP enquiry 与 daemon TCP 许可事务的可观察契约。本协议是自定义模拟格式，不兼容真实 FlexNet wire protocol。

## ADDED Requirements

### Requirement: 由 license 配置或限定范围确定监听端口
模拟器 SHALL 为每个显式声明的 daemon 及 feature 所需的隐式 `default` daemon 启动独立子进程及 TCP listener，daemon PID MUST 与 manager PID 及其他 daemon PID 不同。`DAEMON <name> [PORT <number>]` 的显式 PORT MUST 在 1..65535；不指定时 SHALL 在 **40000..50000（两端包含）** 中随机尝试绑定未占用端口，不得采用 `manager port + offset`、范围外 OS 临时端口或先查空闲再释放的方式。`PORT 0`、重复 daemon/固定端口、与 manager 固定端口冲突及未知 feature 归属 MUST 在启动时被拒绝；显式声明的 `default` 不得重复创建 listener。

#### Scenario: 固定与动态 daemon
- **WHEN** license 含固定端口 daemon、未指定端口 daemon，且有未声明 daemon 的 feature
- **THEN** lmgrd 启动时自动为所有这些 daemon（含 `default`）绑定不同端口，动态端口位于 40000..50000，日志与 enquiry 返回每个实际绑定端口，操作系统报告各子进程 PID 不同

#### Scenario: 占用、冲突与耗尽
- **WHEN** 固定端口被占用、配置端口冲突或动态范围无法绑定可用端口
- **THEN** 整体启动失败、报告原因并释放所有已绑定 socket，不留下可被查询的部分服务或假 ready 日志

### Requirement: 多进程自动启动和统一生命周期
启动 `lmgrd` SHALL 自动派生每个 dummy daemon 子进程，不要求额外运行真实厂商程序。仅当全部子进程及 listener 已准备接受连接时 manager SHALL 响应 enquiry；日志 SHALL 记录每个 daemon 的真实 PID、名称和监听端口。manager 停止或任一 daemon 启动失败时 SHALL 结束全部子进程并释放 listener/日志资源；运行中的 daemon 异常退出 SHALL 明确报不可用，不得默默重置其用量后宣称仍正常服务。

#### Scenario: 就绪和重启
- **WHEN** 启动后发起 enquiry、产生 checkout、停止并重新启动 lmgrd
- **THEN** 首次 enquiry 可获取全部可连接 daemon 端口，操作系统可见与 manager 不同的子 PID；每次日志与实际进程、端口相符，旧进程的端口已释放

#### Scenario: 运行中 worker 异常退出
- **WHEN** 已有 checkout 的 daemon 子进程被异常终止
- **THEN** manager 标记该 daemon 不可用，不能把丢失的在用状态报告为 0 或悄悄重启为空池

### Requirement: 基于证据的流程和传输格式
模拟器 SHALL 以截图 `IMG_3695`～`3698` 的可观察连接阶段作为测试基准：客户端先向 manager enquiry，取得 daemon 端口，再与 daemon 建立单独 TCP 会话，出现 checkout、可持续的心跳、明确的 release/checkin 及连接关闭；同一连接可连续承载多条报文。截图中的 A 类身份报文、B 类发现响应及 C 类 daemon 会话只可把明确显示的字段作为已知事实（见 `evidence.md`）；其余字段 MUST 标为未知，不能把项目自定义 `LMS1` 或猜测的载荷伪装为样本格式。**逐字节匹配真实流量必须先取得经授权的脱敏 PCAP/hex 与对应事件/版本证据**，冻结双向黄金样本和解析规则后才可声称实现该目标；缺少样本时 SHALL 暂停该目标的实施及验收，而非声称兼容。

#### Scenario: 已知连接流程
- **WHEN** 模拟客户端进行 enquiry、按返回端口连接 daemon、checkout、心跳并显式释放
- **THEN** 两个端口的连接方向和阶段顺序与截图一致，套接字关联到不同的 manager/daemon PID，心跳与 FIN 不被当成许可释放

#### Scenario: 缺少原始报文
- **WHEN** 只有截图而没有该会话的完整双向原始字节与事件标注
- **THEN** 逐字节兼容验收标记为 BLOCKED，未知 payload 不填充臆测的 feature、数量或密钥值

### Requirement: lmgrd enquiry 和只读状态
manager SHALL 支持按 daemon 列表、feature、checkout_id 询问对应 daemon 的真实端口，并通过子进程的实时查询汇总健康、状态、checkout 明细和队列；任一子进程不可用时 MUST 报告部分结果/错误而非以 0 代替其在用数；未知 feature/checkout_id SHALL 返回明确的 `UNKNOWN_FEATURE`/`UNKNOWN_CHECKOUT`，不得猜测路由。客户端 SHALL 沿用访问 manager 的 host 并使用返回的 port 连接 daemon，不得将 `SERVER_NAME` 或 `0.0.0.0` 当作连接地址。原有 `lmstat -a/-f/-i` 输出格式 SHALL 不变。

#### Scenario: enquiry 后直连
- **WHEN** 客户端向 lmgrd enquiry 某 feature
- **THEN** 返回唯一 daemon 名与实际端口，客户端可以在该端口建立独立 TCP 连接

### Requirement: daemon 处理许可事务及错误隔离
只有目标 feature 所属 daemon SHALL 执行 CHECKOUT，以及其 checkout_id 的 CHECKIN/RETURN；manager 收到业务请求及错误 daemon 收到事务 MUST 返回明确错误而不代理或改变配额、拒绝计数及 OUT/IN 日志。合法请求 SHALL 保持原有数量、过期、排队、拒绝、归还提升、事件日志及幂等语义；命中 request_id 缓存仍 MUST 验证操作、对象和 daemon 归属。TCP 断线本身 MUST NOT 自动归还许可。daemon SHALL 接受无席位副作用的 `HEARTBEAT` 模拟请求，允许客户端在同一连接上继续发送业务请求；心跳与 TCP 活跃本身 MUST NOT 被当作 checkout 或 checkin 事件。未知 feature 在 enquiry 阶段返回错误，客户端记录本地拒绝；旧服务端 UNSUPPORTED 日志在此情形不再保证产生。

#### Scenario: 正确路由、错误 daemon 与幂等重试
- **WHEN** 客户端 enquiry 后在正确 daemon checkout 并 checkin，又用相同 request_id 向错误 daemon 重试
- **THEN** 正确端点的席位与 OUT/IN 日志按既有规则变化，错误端点不得返回跨 daemon 的缓存成功响应或修改状态

#### Scenario: 并发配额与排队
- **WHEN** 多客户端同时向同一或不同 daemon 请求已耗尽的 feature
- **THEN** 不超卖席位，各 feature 按既有 allow_queue 规则产生 QUEUED/DENIED，manager 只读汇总可观察一致用量

### Requirement: 审计测试可观测性与权威边界
模拟器 SHALL 使宿主机能通过真实 manager PID、daemon 子进程 PID 与 TCP listener/连接关联各端口，且启动日志、enquiry 所报 PID/端口与实际 socket 一致。子进程 MUST 实际存在，不能伪造 PID。端到端测试 SHALL 将 TCP 元数据、debug log（OUT/IN/DENIED）、lmstat 用量快照和模拟引擎状态作为独立观测源进行对账；TCP 流量仅凭元数据 MUST NOT 宣称可还原 feature、用户或席位。即使取得本项目模拟报文的明文字段，也仅标记为“模拟协议已观测”，不得将其当作真实 FlexNet 的通用解析规则。审计测试中的对账结果在日志缺失或各来源冲突时 MUST 标识未知/待核对，不得编造准确用量。

#### Scenario: PID、端口与快照对账
- **WHEN** 监测用例采集进程/监听端口/连接，触发跨 daemon checkout、拒绝与归还，再读取 debug log 与 lmstat
- **THEN** 能关联 manager PID、不同 daemon PID 与各自端口，快照总量和事件计数与各 daemon 状态一致；仅从 TCP 元数据不产生虚假的 feature 用量事件

#### Scenario: 心跳、断线与观测缺口
- **WHEN** 客户端发送 HEARTBEAT 后断线且没有显式 checkin，或审计测试故意丢弃一段日志
- **THEN** 在用量快照中许可仍被占用；心跳/断线不计作归还，丢失日志后的事件推算标为不确定并以新快照对账

### Requirement: 仓库内工具与部署迁移
`lmstat`、workload runner、exporter 验证脚本及 Docker 种子 checkout SHALL 使用新 TCP 流程；Docker 示例 SHALL 为 daemon 配固定端口并发布对应端口。旧 HTTP/JSON API 不再受理，现有 HTTP 客户端 MUST 升级，文档不得承诺真实厂商客户端可以连接此模拟器。

#### Scenario: Docker 与工具回归
- **WHEN** 按更新后的 Docker 示例启动、产生 seed checkout 并执行 lmstat/exporter 查询
- **THEN** seed checkout 通过 daemon TCP 端口成功，lmstat 文本及依赖它的 exporter 指标保持可用
