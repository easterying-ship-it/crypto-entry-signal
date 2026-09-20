# crypto-entry-signal

每天自动抓「加密入场信号日报」需要的五组指标，存成 `data/latest.json`，
供 claude.ai 云端 routine（每天北京 09:00）读取、判断并发 Slack 日报。

为什么要这一层：云端 routine 的沙箱网络策略拦截了 Binance / Farside / CoinGecko /
alternative.me 等数据源，只有 GitHub 可达。所以数据由 GitHub Actions 抓，routine 只读 JSON。

## 流程
1. `.github/workflows/fetch.yml`：每天 00:30 UTC（北京 08:30）运行 `fetch_signals.py`，
   把结果提交到 `data/latest.json` 和 `data/history/YYYY-MM-DD.json`（保留 60 天）。
2. 云端 routine `trig_012BZVYvF8m3XKfMjACqtHtP`（claude.ai/code/routines）09:00 北京时间
   克隆本仓库，读 `data/latest.json`，按框架打分，Slack 私信 Easter。

## 五组指标（字段见 latest.json）
- flows：BTC/ETH 现货 ETF 每日净流入（Farside）、正/负连续天数、稳定币总供应（DefiLlama）
- positioning：资金费率（Binance，年化=8h×3×365）、OI 及 7 日变化、多空账户比
- price：现价、近 7 日收盘、$80k 连续守住天数、SMA50/200 金叉、距 $75k 止损、距 ATH、上周周收
- macro：10Y / DXY / WTI / 黄金（Yahoo，备用 CNBC、FRED）、FOMC / CPI / 期权到期倒计时
- sentiment：Fear & Greed

## 关键价位
写死在 `fetch_signals.py` 顶部 `levels`：hold 80000 / confirm 83000 / stop 75000 / ath 126110，
2026-09-20 设定。价格走远后改这里，并同步改 routine prompt。

## 手动跑一次
Actions 页面 → fetch-signals → Run workflow。本地：`python3 fetch_signals.py data/latest.json`。

## 首次接线（一次性，需要 Easter 本人操作）
1. 在 github.com 新建 **public** 仓库 `easterying-ship-it/crypto-entry-signal`（不要勾 README/.gitignore）。
2. 本机推送：`cd ~/crypto-entry-signal && git push -u origin main`。push 会触发一次 Actions 立即抓数据。
3. （可选，让 routine 直接克隆仓库而不是走 raw URL）在 https://github.com/apps/claude/installations/new
   把 Claude GitHub App 安装到这个仓库，然后在 Claude Code 里说「把 crypto-entry-signal 绑到日报 routine」。
   不装也能跑：routine 会先试 raw.githubusercontent.com，再试 git clone，最后退化为搜索。
