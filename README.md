# rtk-monitor

车载 RTK 定位监控诊断 APP：实时接入定位链路数据、独立解算、自动诊断故障、落盘记录、历史回放。

---

## 快速开始

### 前置条件

- ARM64 Linux 主机（NVIDIA Orin、RK3588 等）
- Python 3.11+（或 Docker）
- 车载网络连通性（与 610、基站/平台广播端口）

### 基本启动

1. **复制示例配置**：
   ```bash
   cp config.yaml.example config.yaml
   ```

2. **编辑配置**（根据现场环境调整网络地址、端口等，参考 [部署指南](docs/deploy.md#32-完整字段说明表)）：
   ```bash
   vim config.yaml
   ```

3. **安装依赖**：
   ```bash
   python3 -m pip install .
   ```

4. **启动应用**：
   ```bash
   python3 -m rtk_monitor.main
   ```

5. **打开浏览器**：
   ```
   http://localhost:8080
   ```
   （或远程访问：`http://<车载电脑IP>:8080`）

### Docker 部署

使用 Docker Compose（详见 [部署指南 §5](docs/deploy.md#5-docker-容器运行)）：

```bash
docker compose up -d --build
```

---

## 文档导航

| 文档 | 内容 |
|---|---|
| [部署指南](docs/deploy.md) | 硬件/网络前置、610 网页配置、config.yaml 全字段说明、裸机与 Docker 两种运行方式、安全姿态、常见问题排查 |
| [MBTiles 卫星影像集成指南](docs/tiles-howto.md) | 矿区影像 → MBTiles 三条转换路线（GeoTIFF、QGIS XYZ、SAS.Planet 下载）、坐标系要求、性能优化、故障排查 |
| [rtkrcv 真机集成核对清单](docs/integration-rtkrcv.md) | 上车前硬件与软件核对清单、Web UI 联调验证项、rtkrcv 进程故障演练、48h 数据库观察项 |
| [WebSocket 消息契约](docs/ws-contract.md) | 实时/回放数据消息格式、安全假设、与 rtkrcv 的同构性 |
| [设计规范](docs/superpowers/specs/2026-08-31-rtk-monitor-design.md) | 项目架构、四路数据接入、诊断规则链（7 条规则）、事件状态机、外部环境事实 |

---

## 项目结构

```
rtk-monitor/
├── src/rtk_monitor/           # Python 应用源码
│   ├── main.py                # 主程序入口、采集协程、诊断引擎
│   ├── config.py              # 配置加载与验证
│   ├── collectors/            # 四路数据采集（TCP/CAN）
│   ├── parsers/               # RTCM/GPCHC/CAN 解析
│   ├── solver/                # rtkrcv 子进程管理
│   ├── diagnosis/             # 诊断规则链、事件状态机
│   ├── storage/               # SQLite 读写、裸流存储
│   ├── api.py                 # FastAPI 服务、WebSocket 推送、回放、报告
│   └── replay.py              # 历史数据回放引擎
├── web/                       # Vue3 + Leaflet 前端单页应用
├── tests/                     # 单元与集成测试（168 项）
├── scripts/                   # 构建脚本（build_rtkrcv.sh 等）
├── config.yaml.example        # 配置文件示例
├── docs/                      # 部署、集成、消息契约文档
└── README.md                  # 本文件
```

---

## 数据流概览

```
采集层
├── Route 1: 差分 RTCM    → 平台广播 TCP 9901
├── Route 2: 原始观测     → 610 Server7 TCP 9902
├── Route 3: 纯卫导解     → 610 Client7 TCP 9903 (GPCHC)
└── Route 4: CAN 融合结果 → SocketCAN can0

        ↓ (落盘 + 入队)

解析 & 诊断
├── RTCM 帧切分与消息号提取
├── GPCHC 解析
├── CAN 解码
├── rtkrcv 独立 RTK 解算
└── 诊断规则链评估（7 条规则）

        ↓

存储 & 推送
├── SQLite: 历元表、事件表、基准点表
├── 裸流文件: YYYYMMDD/hour_RTCM/raw_obs/...
└── WebSocket: 实时状态 & 回放推送

        ↓

前端 (Vue3 + Leaflet)
├── 实时监控页面（状态条、轨迹三色、诊断事件）
├── 事件点击回放
└── 报告统计与打印
```

---

## 核心特性

- **四路全接**：差分、板卡原始观测、纯卫导解、CAN 融合，完整诊断链路
- **独立解算**：内嵌 RTKLIB（rtkrcv）独立 RTK，避免依赖 610 融合结果
- **自动诊断**：7 条规则链，实时检测卫星不足、多路径、基站偏移、模糊度异常等
- **实时+回放**：同构消息格式，前端无需感知数据来源，回放可复盘全程
- **离线地图**：支持 MBTiles 卫星影像，无网络依赖（三条转换路线）
- **故障演练**：支持 rtkrcv 进程杀死演练，验证应用自动恢复能力

---

## 测试

运行完整测试套件（168 项）：

```bash
python3 -m pytest -v
```

快速测试：

```bash
python3 -m pytest -q
```

---

## 许可

内部项目。更多信息请联系项目团队。

---

## 更新日志

### Plan 3b（最新）

- ✓ 前端 UI：实时监控、事件回放、报告生成
- ✓ WebSocket 全改造：实时推送、回放消息同构
- ✓ 部署文档：硬件/网络/配置/常见问题完整指南
- ✓ 集成测试清单：上车前核对点与演练项

### Plan 3a

- ✓ 数据采集与诊断引擎核心
- ✓ SQLite 存储与裸流落盘
- ✓ rtkrcv 子进程管理与解算接入
- ✓ API 与 WebSocket 初版

### Plan 2

- ✓ 配置系统、采集框架、诊断规则定义

### Plan 1

- ✓ 项目初始化、需求确认、架构设计
