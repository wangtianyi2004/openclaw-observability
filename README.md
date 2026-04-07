# openclaw-observability

OpenClaw 可观测性套件，基于 OpenTelemetry + Langfuse + ClickHouse 实现 AI Agent 的全链路追踪、成本统计与性能分析。

## 架构概览

```
OpenClaw Agent
    │
    ├─ session .jsonl ──→ Langfuse Bridge (watchdog)
    │                            │
    └─ OTel Span ──→ OTel Collector ──→ Langfuse Bridge (:9099)
                         │                      │
                         └──→ ClickHouse        └──→ Langfuse
```

- **OTel Collector**：接收 OpenClaw 上报的 OpenTelemetry span，写入 ClickHouse，同时转发给 Langfuse Bridge
- **Langfuse Bridge**（sidecar）：监听 session jsonl 文件变化 + 接收 OTel span，合并后写入 Langfuse，自动为每个 OpenClaw 实例创建独立 Project
- **Langfuse**：LLM 可观测性平台，展示 trace、generation、tool call、cost 等数据
- **ClickHouse**：存储 OTel metrics/logs，供 Grafana 查询分析
- **Grafana**：基于 ClickHouse 数据的自定义监控大盘

## 功能特性

- **自动 Project 创建**：Bridge 启动时根据 `hostname + port` 唯一标识 OpenClaw 实例，自动在 Langfuse 创建对应 Project，无需手动配置
- **多 Agent 支持**：单个 Bridge 可同时监听多个 Agent 的 session 目录
- **完整链路追踪**：每条消息生成一个 Trace，包含多轮 generation、tool call、子 agent 调用
- **精确成本统计**：从 session jsonl 读取真实 token 用量和 cost（含 cache 费用），增量计算每轮消耗
- **Skill Tag 检测**：自动识别 Agent 调用了哪些 Skill，打标签便于过滤
- **Feishu 元数据清洗**：自动剥离消息中的 Feishu 元数据，只保留用户实际问题

## 服务组成

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| langfuse-web | langfuse/langfuse:3 | 3100 | Langfuse Web UI + API |
| langfuse-worker | langfuse/langfuse-worker:3 | 3030 | 异步任务处理 |
| langfuse-bridge | python:3.12-slim | 9099 | OTel span 接收 + session 监听 |
| otel-collector | otel/opentelemetry-collector-contrib | 4518 | OTel 数据采集转发 |
| clickhouse | clickhouse/clickhouse-server | 8123/9000 | OLAP 数据库 |
| grafana | grafana/grafana | 3000 | 监控大盘 |
| langfuse-postgres | postgres:16-alpine | - | Langfuse 元数据存储 |
| langfuse-redis | redis:7-alpine | - | 缓存与队列 |
| langfuse-minio | minio | 9090 | 对象存储 |
| librechat | ghcr.io/danny-avila/librechat | 3080 | Chat UI |

## 快速开始

### 1. 配置环境变量

复制并编辑环境变量文件：

```bash
cp .env.example .env
# 编辑 .env，填写各服务密钥
```

主要配置项：

```bash
# ClickHouse
CLICKHOUSE_PASSWORD=your-password

# Langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_INIT_EMAIL=admin@example.com
LANGFUSE_INIT_PASSWORD=your-password
SALT=your-salt

# PostgreSQL
POSTGRES_USER=langfuse
POSTGRES_PASSWORD=your-password

# OpenClaw session 路径
OPENCLAW_SESSIONS_PATH=/root/.openclaw/agents
```

### 2. 初始化 ClickHouse 表

```bash
docker compose exec clickhouse clickhouse-client \
  --user default --password your-password \
  --database openclaw1 \
  --query "
CREATE TABLE IF NOT EXISTS openclaw_services (
    host_name           String,
    port                UInt16,
    langfuse_project_id String,
    langfuse_public_key String,
    langfuse_secret_key String,
    created_at          DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (host_name, port)
"
```

### 3. 启动服务

```bash
docker compose up -d
```

### 4. 访问各服务

| 服务 | 地址 |
|------|------|
| Langfuse UI | http://your-server:3100 |
| Grafana | http://your-server:3000 |
| LibreChat | http://your-server:3080 |

## Langfuse Bridge 说明

Bridge 是核心组件，以 sidecar 方式与 OpenClaw 一一对应部署。

**自动 Project 创建逻辑：**

1. 启动时读取 `socket.gethostname()` + `BRIDGE_HTTP_PORT` 作为实例唯一标识
2. 查询 ClickHouse `openclaw_services` 表，判断是否已有对应 Project
3. 没有 → 在 Langfuse Postgres 创建新 Project + API Key，写入 ClickHouse 缓存
4. 有 → 直接读取 Key，初始化 Langfuse SDK Client

**Project 命名规则：** `openclaw-{hostname}-{port}`

**数据流：**

```
session .jsonl 变化
    └─→ 解析用户/助手消息、多轮对话、tool call、token 用量
        └─→ 入队等待 OTel processed span

OTel span 到达 (:9099)
    └─→ 提取 trace_id、channel、chatId、sessionKey
        └─→ 存入 span 缓存

Worker 线程
    └─→ 合并 session 数据 + span 数据
        └─→ 写入 Langfuse（1 Trace + N Generation + M Tool Span）
```

## 目录结构

```
.
├── docker-compose.yml          # 服务编排
├── langfuse_bridge.py          # Bridge 核心（v2.5）
├── otel-collector-config.yaml  # OTel Collector 配置
├── sync-prompt.py              # Prompt 同步脚本
├── sync-prompt.cfg             # Prompt 同步配置
├── librechat.yaml              # LibreChat 配置
└── test-agent-graph.py         # Agent graph 测试
```

## 版本历史

**v2.5**
- 启动时自动创建 Langfuse Project，按 `hostname:port` 唯一标识 OpenClaw 实例
- Project/API Key 信息持久化到 ClickHouse `openclaw_services` 表

**v2.4**
- 从 `sessions.json` 读取 resolvedSkills，检测 skill 调用并打标签

**v2.3**
- 修复 13 个问题，包括时间戳精度、cost 统计、tool call 显示、token 增量计算等




