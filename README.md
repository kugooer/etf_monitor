# ETF 定投监测脚本

多 ETF 定投监测工具，支持定时执行、价格监控、MA 偏离度计算和 Bark 通知推送。

## 功能特性

- 多 ETF 监控：通过环境变量配置多个 ETF 代码
- 三层数据源：东方财富 → akshare → baostock（自动降级）
- MA250 均线：计算 250 日移动平均线
- 偏离度通知：无论高于还是低于均线都发送通知
- Bark 推送：支持分组功能
- GitHub Actions：定时自动执行（北京时间 14:00）

## 环境变量

| 变量 | 必需 | 默认值 | 说明 |
|-----|------|--------|------|
| `ETF_CODES` | 否 | `512890` | ETF 代码，多个用逗号分隔 |
| `ETF_NAMES` | 否 | - |ETF名称映射，格式：`512890:红利低波,159919:创业板` |
| `PROXY_URL` | 否 | - | 东方财富 API 中转地址（Cloudflare Worker） |
| `BARK_URL` | 否 | - | Bark 推送 URL |
| `BARK_GROUP` | 否 | - | Bark 分组名称 |

## 市场代码规则

| ETF 代码开头 | 市场 | secid |
|--------------|------|-------|
| 5 开头 | 上海 | `1.{code}` |
| 其他 | 深圳 | `0.{code}` |

## 使用方式

### 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 设置环境变量
export ETF_CODES="512890,159919"
export ETF_NAMES="512890:红利低波ETF,159919:创业板ETF"
export BARK_URL="https://api.day.app/xxx"
export BARK_GROUP="ETF监控"

# 运行
python etf_dingtou_monitor.py
```

### GitHub Actions

在仓库 Settings → Secrets 中配置：

| Secret | 示例 |
|--------|------|
| `ETF_CODES` | `512890,159919` |
| `ETF_NAMES` | `512890:红利低波ETF,159919:创业板ETF` |
| `BARK_URL` | `https://api.day.app/xxx` |
| `BARK_GROUP` | `ETF监控` |

## 通知内容

每次执行会发送通知，包含：
- 当前价格
- MA250 均线值
- 偏离度（百分比）
- 建议（买入/观望）

## 定时任务

- 触发时间：每天 UTC 6:00 = 北京时间 14:00
- 也可通过 GitHub 手动触发

## 文件结构

```
etf_dingtou_monitor.py    # 主脚本
requirements.txt         # Python 依赖
.github/workflows/      # GitHub Actions 配置
cloudflare-worker.js  # Cloudflare Worker 中转脚本（可选）
```

## 依赖

- akshare >= 1.12.0
- baostock >= 0.8.8

## 许可证

MIT