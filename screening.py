#!/usr/bin/env python3
"""
Minervini Trend Template Screener
マーク・ミネルヴィニのトレンドテンプレートを用いた米国株スクリーニング
"""

import io
import os
import time
import logging
from datetime import datetime
from urllib.request import urlopen

import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────────────────────

NASDAQ_LIST_URL = "ftp://ftp.nasdaqtrader.com/SymbolDirectory/nasdaqlisted.txt"
OTHER_LIST_URL  = "ftp://ftp.nasdaqtrader.com/symboldirectory/otherlisted.txt"

MIN_BARS   = 253   # C252 の計算に最低限必要なバー数
BATCH_SIZE = 100   # yfinance 一括取得のバッチサイズ


# ─────────────────────────────────────────────────────────────
# 1. ティッカー取得（Nasdaq FTP → HTTP）
# ─────────────────────────────────────────────────────────────

def _fetch_url(url: str) -> str:
    """HTTP/FTP から文字列を取得"""
    with urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def get_tickers() -> pd.DataFrame:
    """
    Nasdaq の銘柄リストを取得してフィルタリング。
    返り値: DataFrame['symbol', 'name']
    """
    sources = [
        (NASDAQ_LIST_URL, "Symbol"),
        (OTHER_LIST_URL,  "ACT Symbol"),
    ]

    frames = []
    for url, sym_col in sources:
        log.info(f"ティッカー取得中: {url}")
        raw = _fetch_url(url)
        df  = pd.read_csv(io.StringIO(raw), sep="|", dtype=str)

        # 末尾のファイル生成時刻行を除去
        df = df[df[sym_col].notna()]
        df = df[~df[sym_col].str.startswith("File Creation", na=True)]
        df = df[[sym_col, "Security Name"]].rename(
            columns={sym_col: "symbol", "Security Name": "name"}
        )
        frames.append(df)

    tickers = pd.concat(frames, ignore_index=True)

    # ① 記号（ハイフン・ドット等）を含まない → アルファベットのみ
    tickers = tickers[tickers["symbol"].str.match(r"^[A-Z]+$", na=False)]

    # ② 1〜5 文字
    tickers = tickers[tickers["symbol"].str.len().between(1, 5)]

    # ③ Security Name 条件
    include = r"Common Stock|Ordinary Shares|ADR"
    exclude = r"\bETF\b|\bETN\b|Fund|Warrant|Preferred"
    tickers = tickers[
        tickers["name"].str.contains(include, case=False, regex=True, na=False)
        & ~tickers["name"].str.contains(exclude, case=False, regex=True, na=False)
    ]

    tickers = tickers.drop_duplicates("symbol").reset_index(drop=True)
    log.info(f"フィルタリング後の銘柄数: {len(tickers)}")
    return tickers


# ─────────────────────────────────────────────────────────────
# 2. 株価一括取得
# ─────────────────────────────────────────────────────────────

def fetch_all_prices(symbols: list) -> dict:
    """
    全銘柄の終値(過去約2年分)をバッチ単位で取得。
    返り値: {symbol: pd.Series(close)}
    """
    all_close: dict[str, pd.Series] = {}
    total = len(symbols)

    for i in range(0, total, BATCH_SIZE):
        batch = symbols[i : i + BATCH_SIZE]
        log.info(f"  株価取得: {i + len(batch)}/{total} 銘柄完了")

        try:
            raw = yf.download(
                batch,
                period="2y",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if raw.empty:
                continue

            if isinstance(raw.columns, pd.MultiIndex):
                # 複数ティッカー: ('Close', 'AAPL') 形式
                close_df = raw["Close"]
                for sym in batch:
                    if sym not in close_df.columns:
                        continue
                    s = close_df[sym].dropna()
                    if len(s) >= MIN_BARS:
                        all_close[sym] = s
            else:
                # 単一ティッカー
                s = raw["Close"].dropna()
                if len(s) >= MIN_BARS:
                    all_close[batch[0]] = s

        except Exception as exc:
            log.warning(f"バッチ取得エラー (offset={i}): {exc}")

        time.sleep(0.5)  # レート制限対策

    log.info(f"株価取得完了: {len(all_close)}/{total} 銘柄")
    return all_close


# ─────────────────────────────────────────────────────────────
# 3. RS 計算とパーセンタイルランク
# ─────────────────────────────────────────────────────────────

def _calc_rs_score(close: pd.Series) -> float | None:
    """
    Minervini RS スコア計算式。
    C63 は「63営業日前の終値」= close.iloc[-64] (今日=iloc[-1] より63日遡る)
    """
    if len(close) < MIN_BARS:
        return None

    C    = close.iloc[-1]
    C63  = close.iloc[-64]    # 63 営業日前
    C126 = close.iloc[-127]   # 126 営業日前
    C189 = close.iloc[-190]   # 189 営業日前
    C252 = close.iloc[-253]   # 252 営業日前

    # ゼロ除算と負値を防ぐ
    if any(x <= 0 for x in (C63, C126, C189, C252)):
        return None

    return (
        (C - C63)  / C63  * 0.4
        + (C - C126) / C126 * 0.2
        + (C - C189) / C189 * 0.2
        + (C - C252) / C252 * 0.2
    ) * 100


def compute_rs_ranks(close_map: dict) -> dict:
    """
    全銘柄の RS スコアからパーセンタイルランクを算出。
    返り値: {symbol: rank(0〜100)} — 上位 1% が約 99
    """
    scores = {sym: _calc_rs_score(s) for sym, s in close_map.items()}
    scores = {k: v for k, v in scores.items() if v is not None}
    ranks  = pd.Series(scores).rank(pct=True) * 100
    return ranks.to_dict()


# ─────────────────────────────────────────────────────────────
# 4. トレンドテンプレート 8 条件スクリーニング
# ─────────────────────────────────────────────────────────────

def screen_ticker(symbol: str, close: pd.Series, rs_rank: float) -> dict | None:
    """
    8 条件をすべて満たす場合は結果 dict を返す。
    1 つでも失敗すれば None。
    """
    if len(close) < MIN_BARS:
        return None

    cur = float(close.iloc[-1])

    # 移動平均（単純移動平均）
    ma50   = float(close.rolling(50).mean().iloc[-1])
    ma150  = float(close.rolling(150).mean().iloc[-1])
    ma200s = close.rolling(200).mean()
    ma200  = float(ma200s.iloc[-1])
    # 20 営業日前の MA200 (今日=iloc[-1]、20日前=iloc[-21])
    ma200_20d_ago = float(ma200s.iloc[-21])

    # 52 週高値・安値（約 252 営業日）
    hi52 = float(close.iloc[-252:].max())
    lo52 = float(close.iloc[-252:].min())

    # ── 8 条件 ──────────────────────────────────────────────
    passed = (
        cur > ma150 and cur > ma200          # 1: 株価 > MA150, MA200
        and ma150 > ma200                    # 2: MA150 > MA200
        and ma200 > ma200_20d_ago            # 3: MA200 が 20 日前より上昇
        and ma50 > ma150 and ma50 > ma200    # 4: MA50 > MA150, MA200
        and cur > ma50                       # 5: 株価 > MA50
        and cur >= lo52 * 1.30               # 6: 52 週安値から +30% 以上
        and cur >= hi52 * 0.75               # 7: 52 週高値から -25% 以内
        and rs_rank >= 80                    # 8: RS ランク 80 以上
    )

    if not passed:
        return None

    pct_from_high = (cur - hi52) / hi52 * 100

    return {
        "Ticker":             symbol,
        "Price":              round(cur,   2),
        "RS_Rank":            round(rs_rank, 1),
        "MA50":               round(ma50,  2),
        "MA150":              round(ma150, 2),
        "MA200":              round(ma200, 2),
        "52W_High":           round(hi52,  2),
        "52W_Low":            round(lo52,  2),
        "Pct_From_52W_High":  round(pct_from_high, 1),
    }


# ─────────────────────────────────────────────────────────────
# 5. モバイル対応 HTML レポート生成
# ─────────────────────────────────────────────────────────────

def generate_html(df: pd.DataFrame, run_dt: str) -> str:
    """
    GitHub Pages でスマホ表示できるダークテーマ HTML を生成。
    列ヘッダーをタップするとソートできる。
    """
    count = len(df)
    rs90  = int((df["RS_Rank"] >= 90).sum()) if count else 0
    avg_rs = f"{df['RS_Rank'].mean():.1f}" if count else "—"
    max_rs = f"{df['RS_Rank'].max():.0f}" if count else "—"

    if count == 0:
        body_rows = (
            '<tr><td colspan="5" class="empty">'
            "本日は条件を満たす銘柄がありませんでした"
            "</td></tr>"
        )
    else:
        parts = []
        for _, r in df.iterrows():
            rs    = r["RS_Rank"]
            rscls = "rs-hi" if rs >= 90 else "rs-mid" if rs >= 85 else ""
            company = str(r.get("Company", ""))
            company = company[:30] if company != "nan" else ""
            parts.append(
                f'<tr>'
                f'<td class="tk">{r["Ticker"]}</td>'
                f'<td class="nm">{company}</td>'
                f'<td class="nu">${r["Price"]:,.2f}</td>'
                f'<td class="nu {rscls}">{rs:.1f}</td>'
                f'<td class="nu neg">{r["Pct_From_52W_High"]:.1f}%</td>'
                f'</tr>'
            )
        body_rows = "\n".join(parts)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Minervini Screener | {run_dt}</title>
<style>
:root{{
  --bg:#0d1117;--s:#161b22;--b:#30363d;
  --t:#e6edf3;--m:#8b949e;
  --g:#22c55e;--y:#eab308;--r:#ef4444;--p:#a78bfa
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
      background:var(--bg);color:var(--t);font-size:14px;line-height:1.5}}
/* ── ヘッダー ── */
header{{background:var(--s);border-bottom:1px solid var(--b);
        padding:.85rem 1.2rem;position:sticky;top:0;z-index:20}}
header h1{{font-size:1rem;font-weight:700;color:var(--p)}}
header p{{font-size:.7rem;color:var(--m);margin-top:.15rem}}
/* ── KPI カード ── */
.kpi{{display:flex;gap:.7rem;padding:.85rem 1.2rem;
      overflow-x:auto;border-bottom:1px solid var(--b);
      -webkit-overflow-scrolling:touch}}
.card{{background:var(--s);border:1px solid var(--b);border-radius:.6rem;
       padding:.55rem 1rem;flex-shrink:0;min-width:90px;text-align:center}}
.cv{{font-size:1.5rem;font-weight:800;color:var(--p)}}
.cl{{font-size:.62rem;color:var(--m);margin-top:.1rem;white-space:nowrap}}
/* ── テーブル ── */
.wrap{{overflow-x:auto;padding:.8rem;-webkit-overflow-scrolling:touch}}
table{{width:100%;border-collapse:collapse;min-width:420px}}
thead th{{background:var(--s);color:var(--m);font-size:.63rem;font-weight:600;
          letter-spacing:.07em;text-transform:uppercase;
          padding:.5rem .7rem;border-bottom:1px solid var(--b);
          white-space:nowrap;cursor:pointer;user-select:none}}
thead th:hover{{color:var(--t)}}
tbody tr:hover td{{background:#ffffff0a}}
td{{padding:.5rem .7rem;border-bottom:1px solid #21262d;vertical-align:middle}}
.tk{{font-weight:700;color:var(--p);font-size:.9rem;white-space:nowrap}}
.nm{{color:var(--m);font-size:.75rem;max-width:150px;
     overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.nu{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.rs-hi{{color:var(--g);font-weight:700}}
.rs-mid{{color:var(--y)}}
.neg{{color:#f87171}}
.empty{{text-align:center;padding:3rem;color:var(--m);font-size:.85rem}}
/* ── フッター ── */
footer{{text-align:center;color:var(--m);font-size:.65rem;padding:2rem 1rem}}
/* ── スマホ: 会社名列を非表示 ── */
@media(max-width:480px){{
  .nm{{display:none}}
  .cv{{font-size:1.2rem}}
}}
</style>
</head>
<body>
<header>
  <h1>📈 Minervini Trend Template Screener</h1>
  <p>集計: {run_dt} &nbsp;|&nbsp; データ: yfinance / Nasdaq</p>
</header>

<div class="kpi">
  <div class="card"><div class="cv">{count}</div><div class="cl">通過銘柄</div></div>
  <div class="card"><div class="cv">{max_rs}</div><div class="cl">最高RSランク</div></div>
  <div class="card"><div class="cv">{avg_rs}</div><div class="cl">平均RSランク</div></div>
  <div class="card"><div class="cv">{rs90}</div><div class="cl">RS90以上</div></div>
</div>

<div class="wrap">
<table id="tbl">
<thead>
  <tr>
    <th onclick="srt(0)">Ticker ↕</th>
    <th onclick="srt(1)">会社名</th>
    <th onclick="srt(2)" style="text-align:right">株価 ↕</th>
    <th onclick="srt(3)" style="text-align:right">RSランク ↕</th>
    <th onclick="srt(4)" style="text-align:right">高値比 ↕</th>
  </tr>
</thead>
<tbody>
{body_rows}
</tbody>
</table>
</div>

<footer>Minervini Trend Template Screener — 自動生成レポート</footer>

<script>
var dir={{}};
function srt(c){{
  var tb=document.querySelector('#tbl tbody');
  var rs=[].slice.call(tb.rows);
  var asc=!dir[c]; dir={{}}; dir[c]=asc;
  rs.sort(function(a,b){{
    var av=a.cells[c].textContent.replace(/[$%,\\s]/g,'');
    var bv=b.cells[c].textContent.replace(/[$%,\\s]/g,'');
    var an=parseFloat(av), bn=parseFloat(bv);
    if(!isNaN(an)&&!isNaN(bn)) return asc?an-bn:bn-an;
    return asc?av.localeCompare(bv,'ja'):bv.localeCompare(av,'ja');
  }});
  rs.forEach(function(r){{tb.appendChild(r);}});
}}
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────

def main():
    run_dt   = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    date_str = datetime.utcnow().strftime("%Y%m%d")

    # ── 1. ティッカー取得 ────────────────────────────────────
    tickers_df = get_tickers()
    name_map   = dict(zip(tickers_df["symbol"], tickers_df["name"]))
    symbols    = tickers_df["symbol"].tolist()

    # ── 2. 株価一括取得 ──────────────────────────────────────
    log.info(f"株価データ取得開始 ({len(symbols)} 銘柄)...")
    close_map = fetch_all_prices(symbols)

    # ── 3. RS ランク算出 ─────────────────────────────────────
    log.info("RSランクを計算中...")
    rs_ranks = compute_rs_ranks(close_map)
    log.info(f"RSランク算出: {len(rs_ranks)} 銘柄")

    # ── 4. スクリーニング ────────────────────────────────────
    log.info("トレンドテンプレートでスクリーニング中...")
    results = []
    for sym, close in close_map.items():
        rs_rank = rs_ranks.get(sym)
        if rs_rank is None:
            continue
        row = screen_ticker(sym, close, rs_rank)
        if row:
            row["Company"] = name_map.get(sym, "")
            results.append(row)

    # ── 結果 DataFrame 整形 ──────────────────────────────────
    cols = [
        "Ticker", "Company", "Price", "RS_Rank",
        "Pct_From_52W_High", "MA50", "MA150", "MA200",
        "52W_High", "52W_Low",
    ]
    df = (
        pd.DataFrame(results, columns=cols)
        .sort_values("RS_Rank", ascending=False)
        .reset_index(drop=True)
        if results
        else pd.DataFrame(columns=cols)
    )
    log.info(f"スクリーニング通過銘柄数: {len(df)}")

    # ── 5. ファイル出力 ──────────────────────────────────────
    os.makedirs("results", exist_ok=True)
    os.makedirs("docs",    exist_ok=True)

    # CSV（日付付き + 最新版）
    csv_path = f"results/screening_{date_str}.csv"
    df.to_csv(csv_path,            index=False)
    df.to_csv("results/latest.csv", index=False)
    log.info(f"CSV 保存: {csv_path}")

    # HTML（GitHub Pages でスマホ表示）
    html = generate_html(df, run_dt)
    with open("docs/index.html", "w", encoding="utf-8") as fh:
        fh.write(html)
    log.info("HTML レポート保存: docs/index.html")

    return df


if __name__ == "__main__":
    main()
