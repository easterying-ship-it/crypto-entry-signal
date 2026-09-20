#!/usr/bin/env python3
"""Fetch the five indicator groups for the crypto entry-signal daily and write data/latest.json.
Pure stdlib (urllib) so it runs anywhere. Every field is None when a source fails; never fabricated.
"""
import json, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
      "Accept": "*/*"}
ERR = []

import ssl
try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _CTX = ssl.create_default_context()
    try:
        _CTX.load_default_certs()
        _probe = urllib.request.urlopen(urllib.request.Request("https://api.coinbase.com/v2/time", headers=UA), timeout=10, context=_CTX)
    except Exception:
        _CTX = ssl._create_unverified_context()  # local macOS python without root store; CI runners verify normally

import subprocess
def _curl(url, timeout):
    try:
        r = subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", UA["User-Agent"], url],
                           capture_output=True, timeout=timeout + 5)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 and r.stdout else None
    except Exception:
        return None

def get(url, timeout=25, raw=False, retries=2):
    last_err = None
    for attempt in range(retries + 1):
        txt = None
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
                txt = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code == 429 and attempt < retries:
                time.sleep(3 * (attempt + 1)); continue
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:60]}"
            txt = _curl(url, timeout)  # macOS python without a root store: let curl do TLS
            if txt is None and attempt < retries:
                time.sleep(2); continue
        if txt is not None:
            if raw: return txt
            try: return json.loads(txt)
            except Exception as e: last_err = f"bad json: {str(e)[:40]}"
        break
    ERR.append(f"{url.split('?')[0]} -> {last_err}")
    return None

out = {"generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
       "generated_at_bj": (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"),
       "levels": {"hold": 80000, "confirm": 83000, "stop": 75000, "ath": 126110, "set_on": "2026-09-20"}}

# ---------- price ----------
price = {}
cg = get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true")
if cg:
    price["btc"] = cg["bitcoin"]["usd"]; price["btc_24h_pct"] = round(cg["bitcoin"]["usd_24h_change"], 2)
    price["eth"] = cg["ethereum"]["usd"]; price["eth_24h_pct"] = round(cg["ethereum"]["usd_24h_change"], 2)
else:
    cb = get("https://api.coinbase.com/v2/prices/BTC-USD/spot")
    if cb: price["btc"] = float(cb["data"]["amount"])

kl = get("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=210")
if kl:
    closes = [float(k[4]) for k in kl]
    dates = [datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%m-%d") for k in kl]
    # last candle is today's unfinished one; daily closes = all but last
    done_closes, done_dates = closes[:-1], dates[:-1]
    price["daily_closes_last7"] = [{"d": d, "c": round(c)} for d, c in zip(done_dates[-7:], done_closes[-7:])]
    lv = out["levels"]
    n = 0
    for c in reversed(done_closes):
        if c >= lv["hold"]: n += 1
        else: break
    price["days_closed_above_80k"] = n
    price["sma50"] = round(sum(done_closes[-50:]) / 50)
    price["sma200"] = round(sum(done_closes[-200:]) / 200) if len(done_closes) >= 200 else None
    price["golden_cross"] = (price["sma200"] is not None and price["sma50"] > price["sma200"])
    last = price.get("btc") or done_closes[-1]
    price["price_above_sma50_200"] = last > price["sma50"] and (price["sma200"] is None or last > price["sma200"])
    price["pct_to_stop_75k"] = round((last - lv["stop"]) / last * 100, 1)
    price["pct_to_ath"] = round((lv["ath"] - last) / last * 100, 1)
    price["chg_7d_pct"] = round((done_closes[-1] - done_closes[-8]) / done_closes[-8] * 100, 1)
    # last weekly close = close of most recent Sunday (UTC)
    for k in reversed(kl[:-1]):
        d = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
        if d.weekday() == 6:
            price["last_weekly_close"] = {"week_ending": d.strftime("%Y-%m-%d"), "c": round(float(k[4]))}
            break
out["price"] = price

# ---------- positioning ----------
pos = {}
pi = get("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT")
if pi:
    fr = float(pi["lastFundingRate"])
    pos["funding_8h_pct"] = round(fr * 100, 4)
    pos["funding_annualized_pct"] = round(fr * 3 * 365 * 100, 1)
    pos["funding_source"] = "binance"
else:
    ok = get("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP")
    if ok and ok.get("data"):
        fr = float(ok["data"][0]["fundingRate"])
        pos["funding_8h_pct"] = round(fr * 100, 4); pos["funding_annualized_pct"] = round(fr * 3 * 365 * 100, 1)
        pos["funding_source"] = "okx"
oi = get("https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1d&limit=8")
if oi:
    vals = [float(x["sumOpenInterestValue"]) for x in oi]
    pos["oi_usd_bn"] = round(vals[-1] / 1e9, 2)
    pos["oi_chg_7d_pct"] = round((vals[-1] - vals[0]) / vals[0] * 100, 1)
ls = get("https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1d&limit=3")
if ls:
    pos["long_account_pct"] = round(float(ls[-1]["longAccount"]) * 100, 1)
    pos["long_short_ratio"] = round(float(ls[-1]["longShortRatio"]), 2)
out["positioning"] = pos

# ---------- flows (ETF) ----------
def farside(url):
    html = get(url, raw=True)
    if not html: return None
    # rows: <tr><td>DD Mon YYYY</td> ... <td>Total</td> ; Farside prints Total in last column, negatives in (parens)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S)
    seq = []
    for r in rows:
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r, flags=re.S)]
        if len(cells) < 3: continue
        if not re.match(r"\d{1,2} [A-Za-z]{3} \d{4}", cells[0]): continue
        tot = cells[-1].replace(",", "")
        m = re.match(r"^\(?(-?[\d.]+)\)?$", tot)
        if not m: continue
        v = float(m.group(1)); v = -v if tot.startswith("(") else v
        seq.append({"date": cells[0], "total_musd": v})
    return seq[-6:] if seq else None

flows = {}
b = farside("https://farside.co.uk/btc/")
if b:
    flows["btc_etf_daily_musd"] = b
    s = [x["total_musd"] for x in b]
    pos_streak = 0
    for v in reversed(s):
        if v > 0: pos_streak += 1
        else: break
    neg_streak = 0
    for v in reversed(s):
        if v < 0: neg_streak += 1
        else: break
    flows["btc_pos_streak_days"] = pos_streak; flows["btc_neg_streak_days"] = neg_streak
e = farside("https://farside.co.uk/eth/")
if e: flows["eth_etf_daily_musd"] = e
sc = get("https://stablecoins.llama.fi/stablecoins?includePrices=false")
if sc:
    tot = sum((x.get("circulating") or {}).get("peggedUSD", 0) for x in sc.get("peggedAssets", []))
    prev = sum((x.get("circulatingPrevWeek") or {}).get("peggedUSD", 0) for x in sc.get("peggedAssets", []))
    flows["stablecoin_total_bn"] = round(tot / 1e9, 1)
    flows["stablecoin_wow_pct"] = round((tot - prev) / prev * 100, 2) if prev else None
out["flows"] = flows

# ---------- macro ----------
def yahoo_last(sym):
    d = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?range=5d&interval=1d") or get(f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?range=5d&interval=1d")
    try:
        r = d["chart"]["result"][0]
        closes = [c for c in r["indicators"]["quote"][0]["close"] if c is not None]
        return round(r["meta"].get("regularMarketPrice") or closes[-1], 3), round(closes[-2], 3) if len(closes) > 1 else None
    except Exception as ex:
        ERR.append(f"yahoo {sym} -> {type(ex).__name__}"); return None, None
macro = {}
def cnbc_quotes():
    d = get("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=US10Y|.DXY|@CL.1|@GC.1&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json")
    try:
        q = d["FormattedQuoteResult"]["FormattedQuote"]
        m = {}
        for x in q:
            last = float(str(x.get("last", "")).replace("%", "").replace(",", ""))
            m[x["symbol"]] = {"last": last, "chg_pct": x.get("change_pct"), "asof": x.get("last_time")}
        return m
    except Exception as ex:
        ERR.append(f"cnbc quotes -> {type(ex).__name__}"); return None
cq = cnbc_quotes()
keys = [("us10y", "US10Y", "^TNX"), ("dxy", ".DXY", "DX-Y.NYB"), ("wti", "@CL.1", "CL=F"), ("gold", "@GC.1", "GC=F")]
for key, csym, ysym in keys:
    if cq and csym in cq:
        macro[key] = cq[csym]["last"]; macro[key + "_chg_pct"] = cq[csym]["chg_pct"]; macro[key + "_asof"] = cq[csym]["asof"]
    else:
        last, prev = yahoo_last(ysym)
        macro[key] = last; macro[key + "_prev"] = prev
        time.sleep(1.5)
macro["source"] = "cnbc" if cq else "yahoo"
today = datetime.now(timezone.utc).date()
events = {"FOMC": "2026-10-27", "CPI(9月数据)": "2026-10-14"}
# monthly Deribit expiry: last Friday of current/next month
def last_friday(y, m):
    import calendar
    last_day = calendar.monthrange(y, m)[1]
    d = datetime(y, m, last_day).date()
    while d.weekday() != 4: d -= timedelta(days=1)
    return d
lf = last_friday(today.year, today.month)
if lf < today:
    ny, nm = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    lf = last_friday(ny, nm)
events["期权到期"] = lf.isoformat()
macro["events_days_left"] = {k: (datetime.fromisoformat(v).date() - today).days for k, v in events.items()}
macro["events_dates"] = events
out["macro"] = macro

# ---------- sentiment ----------
fg = get("https://api.alternative.me/fng/?limit=2")
if fg:
    out["sentiment"] = {"fear_greed": int(fg["data"][0]["value"]), "label": fg["data"][0]["value_classification"],
                        "fear_greed_prev": int(fg["data"][1]["value"])}
else:
    out["sentiment"] = {}

out["errors"] = ERR
path = sys.argv[1] if len(sys.argv) > 1 else "data/latest.json"
import os; os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
with open(path, "w") as f: json.dump(out, f, ensure_ascii=False, indent=1)
print(json.dumps({k: (v if k != "errors" else len(v)) for k, v in out.items() if k in ("generated_at_bj", "errors")}, ensure_ascii=False))
print("price", out["price"].get("btc"), "| funding", out["positioning"].get("funding_annualized_pct"), "| etf", (out["flows"].get("btc_etf_daily_musd") or [{}])[-1], "| fng", out["sentiment"].get("fear_greed"), "| 10y", out["macro"].get("us10y"))
for e in ERR: print("ERR", e)
