#!/usr/bin/env python3
"""
多ETF 定投监测脚本
通过环境变量 ETF_CODES 指定需要监控的 ETF 代码列表，默认监控 512890。
支持对多个 ETF 的价格、MA250、偏离度计算及通知推送。
"""

import sys
import os
import json
import datetime
import subprocess
import urllib.request
import urllib.parse

def get_baostock_code(code: str) -> str:
    if code.startswith("5"):
        return f"sh.{code}"
    else:
        return f"sz.{code}"

def get_eastmoney_secid(code: str) -> str:
    """根据代码规则判断secid: 5开头=上海(1), 其他=深圳(0)"""
    if code.startswith("5"):
        return f"1.{code}"
    else:
        return f"0.{code}"

# ── 日志 ──────────────────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_FILE = os.path.join(LOG_DIR, "etf_monitor.log")
os.makedirs(LOG_DIR, exist_ok=True)

def log(msg: str, level: str = "INFO"):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ── 配置（支持环境变量）──────────────────────────────────────────────
ETF_CODES = [c.strip() for c in os.getenv("ETF_CODES", "512890").split(",") if c.strip()]

# 名称映射：优先从环境变量 ETF_NAMES 获取，格式: code:name,code:name
# 如: ETF_NAMES=512890:红利低波ETF,510300:沪深300ETF
def load_etf_names() -> dict:
    names_env = os.getenv("ETF_NAMES", "")
    if names_env:
        mapping = {}
        for item in names_env.split(","):
            if ":" in item:
                code, name = item.split(":", 1)
                mapping[code.strip()] = name.strip()
        if mapping:
            return mapping
    return {}

def fetch_etf_name_from_api(code: str) -> str | None:
    """从 akshare 获取 ETF 名称"""
    try:
        import akshare as ak
        df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
        if df is not None and len(df) > 0:
            name = df.iloc[0].get("日期") or df.columns[0]
            return f"{code}ETF"
    except:
        pass
    return None

ETF_NAMES_MAP = load_etf_names()

# 如果名称映射为空，尝试从 API 获取
for code in ETF_CODES:
    if code not in ETF_NAMES_MAP:
        api_name = fetch_etf_name_from_api(code)
        if api_name:
            ETF_NAMES_MAP[code] = api_name

MA_PERIOD = 250

PROXY_URL = os.getenv("PROXY_URL", "")
BARK_URL = os.getenv("BARK_URL", "")
BARK_GROUP = os.getenv("BARK_GROUP", "")

# ── 数据获取 ──────────────────────────────────────────────────────
def fetch_etf_price(code: str) -> float | None:
    """
    尝试多个数据源获取ETF最新价格（收盘价）。
    返回 None 表示所有数据源均失败。
    """
    import urllib.request
    import urllib.error

    # ① 东方财富 HTTP API
    try:
        base = PROXY_URL if PROXY_URL else "https://push2his.eastmoney.com"
        secid = get_eastmoney_secid(code)
        url = (
            f"{base}/api/qt/stock/kline/get"
            f"?secid={secid}&fields1=f1,f2,f3,f4,f5"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            f"&klt=101&fqt=1&end=20500101&lmt=250"
        )
        log(f"[eastmoney-api] 请求URL: {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        klines = data.get("data", {}).get("klines", [])
        if klines:
            log(f"[eastmoney-api] K线数据条数: {len(klines)}")
            log(f"[eastmoney-api] 最新K线: {klines[-1]}")
            last = klines[-1].split(",")
            close = float(last[2])
            log(f"[eastmoney-api] 成功获取 {code} 最新收盘价: {close}")
            return close
    except Exception as e:
        log(f"[eastmoney-api] {code} 获取失败: {e}", "WARN")

    # ② akshare — fund_etf_hist
    try:
        import akshare as ak
        df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
        if df is not None and len(df) > 0:
            latest = df.iloc[-1]
            close = float(latest["收盘"])
            log(f"[akshare] 成功获取 {code} 最新收盘价: {close}")
            return close
    except Exception as e:
        log(f"[akshare] {code} 获取失败: {e}", "WARN")

    # ③ baostock — 日K线
    try:
        import baostock as bs
        lg = bs.login()
        rs = bs.query_history_k_data_plus(
            get_baostock_code(code),
            "date,close",
            start_date=str(datetime.date.today() - datetime.timedelta(days=10)),
            end_date=str(datetime.date.today()),
            frequency="d",
            adjustflag="3"
        )
        bs.logout()
        if rs.error_code == "0":
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if rows:
                for row in reversed(rows):
                    if row[1] and row[1] != "None":
                        close = float(row[1])
                        log(f"[baostock] 成功获取 {code} 最新收盘价: {close}")
                        return close
    except Exception as e:
        log(f"[baostock] {code} 获取失败: {e}", "WARN")

    log(f"[全部数据源失败] 无法获取 {code} 今日价格", "ERROR")
    return None


def fetch_historical_prices(code: str, days: int = 260) -> list[float] | None:
    """
    获取过去 N 个交易日的收盘价列表（用于计算均线）。
    返回升序排列的价格列表，失败返回 None。
    """
    import urllib.request
    import json as _json

    # ① 东方财富 API
    for _ in range(3):
        try:
            base = PROXY_URL if PROXY_URL else "https://push2his.eastmoney.com"
            secid = get_eastmoney_secid(code)
            url = (
                f"{base}/api/qt/stock/kline/get"
                f"?secid={secid}&fields1=f1,f2,f3,f4,f5"
                f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
                f"&klt=101&fqt=1&end=20500101&lmt={days}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            klines = data.get("data", {}).get("klines", [])
            if klines:
                prices = [float(k.split(",")[2]) for k in klines]
                log(f"[eastmoney-api] 成功获取 {code} 历史K线 {len(prices)} 条")
                return prices
        except Exception as e:
            log(f"[eastmoney-api] 重试失败: {e}", "WARN")
            import time
            time.sleep(1)

    # ② baostock 备用
    try:
        import baostock as bs
        bs.login()
        rs = bs.query_history_k_data_plus(
            get_baostock_code(code),
            "date,close",
            start_date=str(datetime.date.today() - datetime.timedelta(days=days)),
            end_date=str(datetime.date.today()),
            frequency="d",
            adjustflag="3"
        )
        bs.logout()
        if rs.error_code == "0":
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if rows:
                prices = [float(row[1]) for row in rows if row[1] and row[1] != "None"]
                log(f"[baostock] 成功获取 {code} 历史K线 {len(prices)} 条")
                return prices
    except Exception as e:
        log(f"[baostock] 历史K线获取失败: {e}", "WARN")

    log(f"[全部数据源失败] 无法获取 {code} 历史K线", "ERROR")
    return None


# ── 均线计算 ──────────────────────────────────────────────────────
def calc_ma(prices: list[float], period: int) -> float | None:
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


# ── 提醒推送 ──────────────────────────────────────────────────────
def send_notification(title: str, body: str):
    if BARK_URL:
        try:
            url = f"{BARK_URL}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"
            if BARK_GROUP:
                url += f"?group={urllib.parse.quote(BARK_GROUP)}"
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", "Mozilla/5.0")
            urllib.request.urlopen(req, timeout=10)
            log("Bark 通知已发送")
        except Exception as e:
            log(f"Bark 通知失败: {e}", "WARN")
    else:
        try:
            script = f'display notification "{body}" with title "{title}"'
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
            log("macOS 通知已发送")
        except Exception as e:
            log(f"通知发送失败: {e}", "WARN")
            print(f"\n{'='*50}")
            print(f"📌 {title}")
            print(body)
            print("=" * 50)


def process_etf(code: str):
    """处理单个 ETF 的监测逻辑：获取当前价、历史价、MA、偏离度，并在低于均线时发送通知"""
    name = ETF_NAMES_MAP.get(code, code)
    today = datetime.date.today()
    log(f"[{code}] 监测开始，日期: {today}, 名称: {name}")

    # ① 获取当前价格
    current_price = fetch_etf_price(code)
    if current_price is None:
        send_notification(
            f"{name} 数据获取异常",
            f"日期: {today}\n未能获取今日价格，请检查数据源。"
        )
        return

    # ② 获取历史价格 → 计算 MA250
    prices = fetch_historical_prices(code, days=MA_PERIOD + 50)
    if prices is None or len(prices) < MA_PERIOD:
        send_notification(
            f"{name} 数据不足",
            f"历史数据不足 {MA_PERIOD} 条，无法计算均线。"
        )
        return

    ma250 = calc_ma(prices, MA_PERIOD)
    deviation = (current_price - ma250) / ma250 * 100   # 单位: %

    log(f"当前价格: {current_price:.4f}")
    log(f"MA250:    {ma250:.4f}")
    log(f"偏离度:   {deviation:+.4f}%")

    # ③ 判断 & 输出 - 无论正负都发送通知
    if deviation < 0:
        status = "✅ 低于均线 → 建议定投买入"
        hint = "当前价格低于250日均线，适合定投买入"
    else:
        status = "ℹ️ 高于/等于均线，暂不定投"
        hint = "价格位于均线上方，耐心等待回调"

    # ④ 发送通知
    title = f"📈 {name} 定投提醒"
    body_lines = [
        f"📅 日期: {today}",
        f"💰 当前价格: ¥{current_price:.4f}",
        f"📊 250日均线: ¥{ma250:.4f}",
        f"📉 偏离度: {deviation:+.2f}%",
        "",
        f"💡 建议: {hint}",
        "",
        f"📌 {status}",
    ]
    body = "\n".join(body_lines)
    send_notification(title, body)
    log(f"提醒已推送: {status}")


# ── 主逻辑 ────────────────────────────────────────────────────────
def main():
    today = datetime.date.today()
    log(f"========== {today} 多ETF 定投监测开始 ==========")

    # 遍历配置的 ETF 列表，逐个处理
    for code in ETF_CODES:
        process_etf(code)


if __name__ == "__main__":
    main()
