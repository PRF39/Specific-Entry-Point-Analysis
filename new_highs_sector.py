#!/usr/bin/env python3
"""
52週新高値セクター分析スクリプト
強気相場の初期にリーダーとなるセクターを特定する
"""

import io
import json
import os
import sys
import time
import logging
from datetime import datetime
from urllib.request import urlopen

import pandas as pd
import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# 定数
# ────────────────────────────────────────────────────────────
NASDAQ_LIST_URL   = "ftp://ftp.nasdaqtrader.com/SymbolDirectory/nasdaqlisted.txt"
OTHER_LIST_URL    = "ftp://ftp.nasdaqtrader.com/symboldirectory/otherlisted.txt"

MIN_BARS          = 200    # 52週高値計算に必要な最小バー数
BATCH_SIZE        = 100    # yfinance バッチサイズ
AT_HIGH_PCT       = -1.0   # 「新高値」閾値（52週高値の1%以内）
NEAR_HIGH_PCT     = -5.0   # 「高値近接」閾値（52週高値の5%以内）
SECTOR_CACHE_FILE = "results/sector_cache.json"


# ────────────────────────────────────────────────────────────
# 1. ティッカー取得（screening.py と同じロジック）
# ────────────────────────────────────────────────────────────

def _fetch_url(url: str) -> str:
    with urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def get_tickers() -> pd.DataFrame:
    sources = [
        (NASDAQ_LIST_URL, "Symbol"),
        (OTHER_LIST_URL,  "ACT Symbol"),
    ]
    frames = []
    for url, sym_col in sources:
        log.info(f"ティッカー取得中: {url}")
        raw = _fetch_url(url)
        df  = pd.read_csv(io.StringIO(raw), sep="|", dtype=str)
        df  = df[df[sym_col].notna()]
        df  = df[~df[sym_col].str.startswith("File Creation", na=True)]
        df  = df[[sym_col, "Security Name"]].rename(
            columns={sym_col: "symbol", "Security Name": "name"}
        )
        frames.append(df)

    tickers = pd.concat(frames, ignore_index=True)
    tickers = tickers[tickers["symbol"].str.match(r"^[A-Z]+$", na=False)]
    tickers = tickers[tickers["symbol"].str.len().between(1, 5)]
    include = r"Common Stock|Ordinary Shares|ADR"
    exclude = r"\bETF\b|\bETN\b|Fund|Warrant|Preferred"
    tickers = tickers[
        tickers["name"].str.contains(include, case=False, regex=True, na=False)
        & ~tickers["name"].str.contains(exclude, case=False, regex=True, na=False)
    ]
    tickers = tickers.drop_duplicates("symbol").reset_index(drop=True)
    log.info(f"フィルタリング後の銘柄数: {len(tickers)}")
    return tickers


# ────────────────────────────────────────────────────────────
# 2. 株価データ取得（過去1年分）
# ────────────────────────────────────────────────────────────

def fetch_prices(symbols: list) -> dict:
    all_close: dict[str, pd.Series] = {}
    total = len(symbols)

    for i in range(0, total, BATCH_SIZE):
        batch = symbols[i : i + BATCH_SIZE]
        log.info(f"  株価取得: {i + len(batch)}/{total} 銘柄完了")
        try:
            raw = yf.download(
                batch,
                period="1y",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if raw.empty:
                continue

            if isinstance(raw.columns, pd.MultiIndex):
                close_df = raw["Close"]
                for sym in batch:
                    if sym not in close_df.columns:
                        continue
                    s = close_df[sym].dropna()
                    if len(s) >= MIN_BARS:
                        all_close[sym] = s
            else:
                s = raw["Close"].dropna()
                if len(s) >= MIN_BARS:
                    all_close[batch[0]] = s

        except Exception as exc:
            log.warning(f"バッチ取得エラー (offset={i}): {exc}")

        time.sleep(0.5)

    log.info(f"株価取得完了: {len(all_close)}/{total} 銘柄")
    return all_close


# ────────────────────────────────────────────────────────────
# 3. 52週高値圏の銘柄を特定
# ────────────────────────────────────────────────────────────

def find_near_highs(close_map: dict) -> pd.DataFrame:
    rows = []
    for sym, close in close_map.items():
        cur  = float(close.iloc[-1])
        hi52 = float(close.max())
        if hi52 <= 0:
            continue
        pct = (cur - hi52) / hi52 * 100
        if pct >= NEAR_HIGH_PCT:
            rows.append({
                "Ticker":            sym,
                "Price":             round(cur,  2),
                "52W_High":          round(hi52, 2),
                "Pct_From_52W_High": round(pct,  1),
            })

    df = (
        pd.DataFrame(rows)
        .sort_values("Pct_From_52W_High", ascending=False)
        .reset_index(drop=True)
        if rows
        else pd.DataFrame(columns=["Ticker", "Price", "52W_High", "Pct_From_52W_High"])
    )
    at_count = int((df["Pct_From_52W_High"] >= AT_HIGH_PCT).sum()) if not df.empty else 0
    log.info(f"高値近接銘柄数 (5%以内): {len(df)}  うち新高値 (1%以内): {at_count}")
    return df


# ────────────────────────────────────────────────────────────
# 4. セクター情報取得（キャッシュ付き）
# ────────────────────────────────────────────────────────────

def load_sector_cache() -> dict:
    if os.path.exists(SECTOR_CACHE_FILE):
        try:
            with open(SECTOR_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_sector_cache(cache: dict) -> None:
    with open(SECTOR_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def fetch_sectors(tickers: list, cache: dict) -> dict:
    to_fetch = [t for t in tickers if t not in cache]
    log.info(
        f"セクター取得: キャッシュ済み {len(tickers) - len(to_fetch)} 件, "
        f"新規フェッチ {len(to_fetch)} 件"
    )

    for i, ticker in enumerate(to_fetch):
        if i % 50 == 0 and i > 0:
            log.info(f"  セクター取得進捗: {i}/{len(to_fetch)}")
        try:
            info = yf.Ticker(ticker).info
            sector = info.get("sector") or "Unknown"
        except Exception:
            sector = "Unknown"
        cache[ticker] = sector
        time.sleep(0.25)

    return {t: cache.get(t, "Unknown") for t in tickers}


# ────────────────────────────────────────────────────────────
# 5. セクター集計
# ────────────────────────────────────────────────────────────

def aggregate_sectors(stocks_df: pd.DataFrame) -> pd.DataFrame:
    if stocks_df.empty or "Sector" not in stocks_df.columns:
        return pd.DataFrame(columns=[
            "Sector", "AT_High_Count", "Near_High_Count",
            "Avg_Pct_From_High", "Top_Tickers",
        ])

    rows = []
    for sector, grp in stocks_df.groupby("Sector"):
        at_count   = int((grp["Pct_From_52W_High"] >= AT_HIGH_PCT).sum())
        near_count = len(grp)
        avg_pct    = round(grp["Pct_From_52W_High"].mean(), 1)
        top5       = (
            grp.sort_values("Pct_From_52W_High", ascending=False)
               .head(5)["Ticker"]
               .tolist()
        )
        rows.append({
            "Sector":            sector,
            "AT_High_Count":     at_count,
            "Near_High_Count":   near_count,
            "Avg_Pct_From_High": avg_pct,
            "Top_Tickers":       ", ".join(top5),
        })

    return (
        pd.DataFrame(rows)
        .sort_values("AT_High_Count", ascending=False)
        .reset_index(drop=True)
    )


# ────────────────────────────────────────────────────────────
# 6. HTML 生成（screening.py と同じダークテーマ）
# ────────────────────────────────────────────────────────────

def generate_html(sector_df: pd.DataFrame, stocks_df: pd.DataFrame, run_dt: str) -> str:
    total_near  = len(stocks_df)
    total_at    = int((stocks_df["Pct_From_52W_High"] >= AT_HIGH_PCT).sum()) if not stocks_df.empty else 0
    num_sectors = len(sector_df)
    max_at      = int(sector_df["AT_High_Count"].max()) if not sector_df.empty else 1

    # ── セクターテーブル ──
    if sector_df.empty:
        sector_rows = '<tr><td colspan="5" class="empty">データなし</td></tr>'
    else:
        parts = []
        for rank, (_, r) in enumerate(sector_df.iterrows()):
            at_cnt    = r["AT_High_Count"]
            bar_width = int(at_cnt / max(max_at, 1) * 100)
            rank_cls  = "rank-1" if rank == 0 else "rank-2" if rank == 1 else "rank-3" if rank == 2 else ""
            parts.append(
                f'<tr>'
                f'<td class="sec {rank_cls}">{r["Sector"]}</td>'
                f'<td class="nu">'
                f'  <div class="bar-cell">'
                f'    <div class="bar-track"><div class="bar-fill" style="width:{bar_width}%"></div></div>'
                f'    <span class="hi fw">{at_cnt}</span>'
                f'  </div>'
                f'</td>'
                f'<td class="nu">{r["Near_High_Count"]}</td>'
                f'<td class="nu muted">{r["Avg_Pct_From_High"]:.1f}%</td>'
                f'<td class="tk-list">{r["Top_Tickers"]}</td>'
                f'</tr>'
            )
        sector_rows = "\n".join(parts)

    # ── 個別銘柄テーブル ──
    if stocks_df.empty:
        stock_rows = '<tr><td colspan="4" class="empty">データなし</td></tr>'
    else:
        parts = []
        for _, r in stocks_df.iterrows():
            pct     = r["Pct_From_52W_High"]
            pct_cls = "hi fw" if pct >= AT_HIGH_PCT else "muted"
            sector  = r.get("Sector", "")
            tv_url  = f"https://www.tradingview.com/chart/?symbol={r['Ticker']}"
            parts.append(
                f'<tr>'
                f'<td class="tk"><a href="{tv_url}" target="_blank" rel="noopener">{r["Ticker"]}</a></td>'
                f'<td class="nu">${r["Price"]:,.2f}</td>'
                f'<td class="nu {pct_cls}">{pct:.1f}%</td>'
                f'<td class="sec">{sector}</td>'
                f'</tr>'
            )
        stock_rows = "\n".join(parts)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>52週新高値セクター分析 | {run_dt}</title>
<style>
:root{{
  --bg:#0d1117;--s:#161b22;--b:#30363d;
  --t:#e6edf3;--m:#8b949e;
  --g:#22c55e;--y:#eab308;--r:#ef4444;--p:#a78bfa
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
      background:var(--bg);color:var(--t);font-size:14px;line-height:1.5}}
header{{background:var(--s);border-bottom:1px solid var(--b);
        padding:.85rem 1.2rem;position:sticky;top:0;z-index:20}}
header h1{{font-size:1rem;font-weight:700;color:var(--p)}}
header p{{font-size:.7rem;color:var(--m);margin-top:.15rem}}
.kpi{{display:flex;gap:.7rem;padding:.85rem 1.2rem;
      overflow-x:auto;border-bottom:1px solid var(--b);
      -webkit-overflow-scrolling:touch}}
.card{{background:var(--s);border:1px solid var(--b);border-radius:.6rem;
       padding:.55rem 1rem;flex-shrink:0;min-width:90px;text-align:center}}
.cv{{font-size:1.5rem;font-weight:800;color:var(--p)}}
.cl{{font-size:.62rem;color:var(--m);margin-top:.1rem;white-space:nowrap}}
h2{{padding:.9rem 1.2rem .4rem;font-size:.72rem;color:var(--m);
    letter-spacing:.1em;text-transform:uppercase;border-top:1px solid var(--b)}}
.wrap{{overflow-x:auto;padding:0 .8rem .8rem;-webkit-overflow-scrolling:touch}}
table{{width:100%;border-collapse:collapse;min-width:380px}}
thead th{{background:var(--s);color:var(--m);font-size:.63rem;font-weight:600;
          letter-spacing:.07em;text-transform:uppercase;
          padding:.5rem .7rem;border-bottom:1px solid var(--b);
          white-space:nowrap;cursor:pointer;user-select:none}}
thead th:hover{{color:var(--t)}}
tbody tr:hover td{{background:#ffffff0a}}
td{{padding:.45rem .7rem;border-bottom:1px solid #21262d;vertical-align:middle}}
.sec{{font-size:.82rem}}
.rank-1{{color:var(--g);font-weight:700}}
.rank-2{{color:var(--y);font-weight:700}}
.rank-3{{color:var(--p)}}
.tk{{font-weight:700;color:var(--p);font-size:.9rem;white-space:nowrap}}
.tk a{{color:inherit;text-decoration:none}}
.tk a:hover{{text-decoration:underline}}
.tk-list{{color:var(--m);font-size:.72rem;min-width:160px}}
.nu{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.hi{{color:var(--g)}}
.muted{{color:#f87171}}
.fw{{font-weight:700}}
.empty{{text-align:center;padding:3rem;color:var(--m);font-size:.85rem}}
.bar-cell{{display:flex;align-items:center;gap:.5rem;justify-content:flex-end}}
.bar-track{{width:80px;height:6px;background:var(--b);border-radius:3px;flex-shrink:0}}
.bar-fill{{height:6px;background:var(--g);border-radius:3px}}
footer{{text-align:center;color:var(--m);font-size:.65rem;padding:2rem 1rem}}
@media(max-width:480px){{
  .cv{{font-size:1.2rem}}
  .tk-list{{display:none}}
  .bar-track{{width:50px}}
}}
</style>
</head>
<body>
<header>
  <h1>📊 52週新高値セクター分析</h1>
  <p>集計: {run_dt} &nbsp;|&nbsp; データ: yfinance / Nasdaq</p>
</header>

<div class="kpi">
  <div class="card">
    <div class="cv">{total_at}</div>
    <div class="cl">新高値銘柄数<br>（1%以内）</div>
  </div>
  <div class="card">
    <div class="cv">{total_near}</div>
    <div class="cl">高値近接銘柄数<br>（5%以内）</div>
  </div>
  <div class="card">
    <div class="cv">{num_sectors}</div>
    <div class="cl">対象セクター数</div>
  </div>
</div>

<h2>セクター別ランキング（新高値数順）</h2>
<div class="wrap">
<table id="sec-tbl">
<thead>
  <tr>
    <th onclick="srt('sec-tbl',0)">セクター ↕</th>
    <th onclick="srt('sec-tbl',1)" style="text-align:right">新高値数 ↑↓</th>
    <th onclick="srt('sec-tbl',2)" style="text-align:right">高値近接数 ↕</th>
    <th onclick="srt('sec-tbl',3)" style="text-align:right">平均高値比 ↕</th>
    <th>代表銘柄（上位5）</th>
  </tr>
</thead>
<tbody>
{sector_rows}
</tbody>
</table>
</div>

<h2>個別銘柄リスト（高値近接順）</h2>
<div class="wrap">
<table id="stk-tbl">
<thead>
  <tr>
    <th onclick="srt('stk-tbl',0)">Ticker ↕</th>
    <th onclick="srt('stk-tbl',1)" style="text-align:right">株価 ↕</th>
    <th onclick="srt('stk-tbl',2)" style="text-align:right">高値比 ↕</th>
    <th onclick="srt('stk-tbl',3)">セクター ↕</th>
  </tr>
</thead>
<tbody>
{stock_rows}
</tbody>
</table>
</div>

<footer>52週新高値セクター分析 — 自動生成レポート</footer>

<script>
var _dir={{}};
function srt(tid,c){{
  var tb=document.querySelector('#'+tid+' tbody');
  var rows=[].slice.call(tb.rows);
  var key=tid+'_'+c;
  var asc=!_dir[key]; _dir={{}};_dir[key]=asc;
  rows.sort(function(a,b){{
    var ac=a.cells[c], bc=b.cells[c];
    if(!ac||!bc) return 0;
    var av=ac.textContent.replace(/[$%,\\s]/g,'');
    var bv=bc.textContent.replace(/[$%,\\s]/g,'');
    var an=parseFloat(av), bn=parseFloat(bv);
    if(!isNaN(an)&&!isNaN(bn)) return asc?an-bn:bn-an;
    return asc?av.localeCompare(bv,'ja'):bv.localeCompare(av,'ja');
  }});
  rows.forEach(function(r){{tb.appendChild(r);}});
}}
</script>
</body>
</html>"""


# ────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────

def main():
    refresh_cache = "--refresh-cache" in sys.argv
    run_dt   = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    date_str = datetime.utcnow().strftime("%Y%m%d")

    os.makedirs("results", exist_ok=True)
    os.makedirs("docs",    exist_ok=True)

    # 1. ティッカー取得
    tickers_df = get_tickers()
    symbols    = tickers_df["symbol"].tolist()

    # 2. 株価データ取得（1年分）
    log.info(f"株価データ取得開始 ({len(symbols)} 銘柄)...")
    close_map = fetch_prices(symbols)

    # 3. 52週高値圏の銘柄を特定
    log.info("52週高値圏の銘柄を特定中...")
    stocks_df = find_near_highs(close_map)

    if stocks_df.empty:
        log.warning("高値近接銘柄が見つかりませんでした")
        stocks_df["Sector"] = pd.Series(dtype=str)
    else:
        # 4. セクター情報取得（高値近接銘柄のみ）
        sector_cache = {} if refresh_cache else load_sector_cache()
        near_tickers = stocks_df["Ticker"].tolist()
        sector_map   = fetch_sectors(near_tickers, sector_cache)
        save_sector_cache(sector_cache)
        stocks_df["Sector"] = stocks_df["Ticker"].map(sector_map).fillna("Unknown")

    # 5. セクター集計
    log.info("セクター別に集計中...")
    sector_df = aggregate_sectors(stocks_df)
    log.info(f"セクター数: {len(sector_df)}")

    # 6. 出力
    sector_df.to_csv(f"results/new_highs_sector_{date_str}.csv", index=False)
    sector_df.to_csv("results/new_highs_sector.csv", index=False)
    stocks_df.to_csv(f"results/new_highs_stocks_{date_str}.csv", index=False)
    stocks_df.to_csv("results/new_highs_stocks.csv", index=False)
    log.info("CSV 保存完了")

    html = generate_html(sector_df, stocks_df, run_dt)
    with open("docs/new_highs_sector.html", "w", encoding="utf-8") as fh:
        fh.write(html)
    log.info("HTML レポート保存: docs/new_highs_sector.html")

    return sector_df


if __name__ == "__main__":
    main()
