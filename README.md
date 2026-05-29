# Linux Mihomo 旁路由

在 Phicomm N1（或其它 OpenWrt/Armbian 设备）上运行 [Mihomo](https://github.com/MetaCubeX/mihomo) 作为局域网透明代理旁路由，并提供 Web 管理面板。

## 功能

- **Mihomo 旁路由**：TCP redir、DNS、规则分流
- **Web 面板**（`panel/`）：概览、节点、机场订阅、设备 MAC 策略、规则、服务管理
- **机场订阅**：支持 Mihomo `proxy-providers` 的 **HTTP 远程订阅**、**本地 YAML 文件**、**内联节点**；可选 User-Agent / 请求头（Token 鉴权）
- **设备管理**：按 **MAC** 登记允许/直连/禁止，DHCP 换 IP 策略仍生效

## 目录结构

```
├── config.example.yaml   # 配置模板
├── panel/                # Flask Web 面板
├── install-on-n1.sh      # 安装 Mihomo 核心
├── install-panel.sh      # 部署面板到 N1
├── setup-gateway.sh      # 网关与 iptables
└── download-geodata.sh   # 下载 GEO 数据
```

## 快速开始

1. 复制配置：`cp config.example.yaml config.yaml`，编辑订阅 URL。
2. 将项目同步到 N1 后执行 `install-on-n1.sh`、`setup-gateway.sh`、`install-panel.sh`。
3. 浏览器访问 `http://<N1_IP>:8088`（默认密码：见安装脚本说明）。

## 面板：添加机场

| 方式 | 说明 |
|------|------|
| 远程订阅 (HTTP) | 机场 Clash / Meta / Mihomo 订阅链接 |
| 本地文件 | `./providers/xxx.yaml` |
| 内联节点 | 粘贴 YAML 节点列表 |
| Token 订阅 | HTTP + `Authorization` 等请求头 |

## 许可

个人学习使用；订阅链接与节点请遵守当地法律法规及服务商条款。
