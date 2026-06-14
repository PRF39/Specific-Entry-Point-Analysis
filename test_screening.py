#!/usr/bin/env python3
"""
screening.py のコンポーネントテスト
- 少数銘柄で各ステップを検証
- 全件実行（30〜90分）は不要
"""

import sys
import traceback
import io
import time
from urllib.request import urlopen, Request

import pandas as pd
import numpy as np
import yfinance as yf


# ────────────────────────────────────────────
# テスト対象の銘柄（著名な成長株 + 意図的な除外候補）
# ────────────────────────────────────────────
TEST_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN",
                "META", "GOOGL", "AVGO", "AMD", "CRWD"]

PASS = "[OK]"
FAIL = "[NG]"
WARN = "[!!]"


def section(title: str):
    print(f"\n{'─'*50}")
    print(f"  {title}")
    print('─'*50)


# ────────────────────────────────────────────
# テスト 1: Nasdaq ティッカー取得
# ────────────────────────────────────────────
def test_ticker_fetch():
    section("テスト 1: Nasdaq ティッカー取得")
    try:
        from screening import get_tickers
        df = get_tickers()
        assert len(df) > 1000, f"銘柄数が少なすぎます: {len(df)}"
        assert "symbol" in df.columns and "name" in df.columns

        # フィルタリング確認
        has_hyphen = df["symbol"].str.contains(r"[-.]").any()
        too_long   = (df["symbol"].str.len() > 5).any()
        print(f"{PASS} 取得銘柄数: {len(df)}")
        print(f"{FAIL if has_hyphen else PASS} ハイフン・ドット除外: {'失敗' if has_hyphen else 'OK'}")
        print(f"{FAIL if too_long   else PASS} 6文字以上除外:       {'失敗' if too_long else 'OK'}")

        # サンプル表示
        print("\n  先頭5銘柄:")
        print(df.head().to_string(index=False))
        return True, len(df)
    except Exception as e:
        print(f"{FAIL} エラー: {e}")
        traceback.print_exc()
        return False, 0


# ────────────────────────────────────────────
# テスト 2: yfinance 株価取得
# ────────────────────────────────────────────
def test_price_fetch():
    section("テスト 2: yfinance 株価取得（10銘柄）")
    try:
        raw = yf.download(
            TEST_SYMBOLS,
            period="2y",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        print(f"  DataFrame shape: {raw.shape}")
        print(f"  columns type: {type(raw.columns).__name__}")
        print(f"  columns levels: {raw.columns.nlevels if hasattr(raw.columns, 'nlevels') else 'N/A'}")

        if raw.empty:
            print(f"{FAIL} データが空です")
            return False, {}

        # Close 抽出
        close_map = {}
        if isinstance(raw.columns, pd.MultiIndex):
            close_df = raw["Close"]
            for sym in TEST_SYMBOLS:
                if sym in close_df.columns:
                    s = close_df[sym].dropna()
                    close_map[sym] = s
                    print(f"  {sym}: {len(s)} バー, 最新値=${s.iloc[-1]:.2f}")
        else:
            # 単一ティッカーの場合
            sym = TEST_SYMBOLS[0]
            s = raw["Close"].dropna()
            close_map[sym] = s
            print(f"  {sym}: {len(s)} バー, 最新値=${s.iloc[-1]:.2f}")

        ok_count = sum(1 for s in close_map.values() if len(s) >= 253)
        print(f"\n{PASS} 取得成功: {len(close_map)}/{len(TEST_SYMBOLS)} 銘柄")
        print(f"{PASS if ok_count == len(close_map) else WARN} 253バー以上: {ok_count}/{len(close_map)} 銘柄")
        return True, close_map

    except Exception as e:
        print(f"{FAIL} エラー: {e}")
        traceback.print_exc()
        return False, {}


# ────────────────────────────────────────────
# テスト 3: RS 計算
# ────────────────────────────────────────────
def test_rs_calculation(close_map: dict):
    section("テスト 3: RS 計算とパーセンタイルランク")
    try:
        from screening import compute_rs_ranks, _calc_rs_score

        # 個別スコア確認
        print("  個別 RS スコア（生値）:")
        for sym, close in close_map.items():
            score = _calc_rs_score(close)
            print(f"    {sym}: {score:.2f}" if score else f"    {sym}: None（データ不足）")

        # ランク計算
        ranks = compute_rs_ranks(close_map)
        print(f"\n  パーセンタイルランク（この{len(TEST_SYMBOLS)}銘柄内）:")
        for sym, rank in sorted(ranks.items(), key=lambda x: -x[1]):
            bar = "#" * int(rank / 10)
            print(f"    {sym:6s}: {rank:5.1f}  {bar}")

        assert len(ranks) > 0
        assert all(0 <= v <= 100 for v in ranks.values())
        print(f"\n{PASS} RS ランク計算: OK（{len(ranks)} 銘柄）")
        return True, ranks
    except Exception as e:
        print(f"{FAIL} エラー: {e}")
        traceback.print_exc()
        return False, {}


# ────────────────────────────────────────────
# テスト 4: トレンドテンプレート条件チェック
# ────────────────────────────────────────────
def test_trend_template(close_map: dict, rs_ranks: dict):
    section("テスト 4: トレンドテンプレート 8 条件")

    # テスト用に全銘柄の RS ランクを再計算（全件でのランクではなくサンプル内ランク）
    # 条件 8（RS >= 80）を強制通過させるため、ランクを 85 にオーバーライドして
    # 他の 7 条件のみ確認するモードと、実際のランクで確認するモードの両方を実施

    try:
        from screening import screen_ticker

        print("  [モード A] 実際の RS ランクで評価（サンプル内ランク）:")
        passed_a = []
        for sym, close in close_map.items():
            rank = rs_ranks.get(sym, 0)
            result = screen_ticker(sym, close, rank)
            status = PASS if result else "  "
            print(f"    {status} {sym:6s} (RSランク={rank:.1f}): {'通過' if result else '除外'}")
            if result:
                passed_a.append(sym)

        print(f"\n  [モード B] RS条件を免除して残り7条件のみ評価（RS=85 固定）:")
        passed_b = []
        for sym, close in close_map.items():
            result = screen_ticker(sym, close, 85.0)
            status = PASS if result else "  "
            print(f"    {status} {sym:6s}: {'通過' if result else '除外'}")
            if result:
                passed_b.append(sym)

        if passed_b:
            print(f"\n  モードBの通過銘柄詳細:")
            for sym in passed_b:
                r = screen_ticker(sym, close_map[sym], 85.0)
                if r:
                    print(f"    {sym}: 株価=${r['Price']:.2f}, MA50=${r['MA50']:.2f}, "
                          f"MA200=${r['MA200']:.2f}, 高値比={r['Pct_From_52W_High']:.1f}%")

        print(f"\n{PASS} screen_ticker 関数: 正常動作")
        print(f"  モードA（実ランク）通過: {len(passed_a)} 銘柄 {passed_a}")
        print(f"  モードB（7条件）通過:   {len(passed_b)} 銘柄 {passed_b}")
        return True
    except Exception as e:
        print(f"{FAIL} エラー: {e}")
        traceback.print_exc()
        return False


# ────────────────────────────────────────────
# テスト 5: HTML 生成
# ────────────────────────────────────────────
def test_html_generation(close_map: dict, rs_ranks: dict):
    section("テスト 5: HTML レポート生成")
    try:
        from screening import screen_ticker, generate_html

        results = []
        for sym, close in close_map.items():
            rank = rs_ranks.get(sym, 85.0)
            r = screen_ticker(sym, close, 85.0)   # RS免除でサンプルを作る
            if r:
                r["Company"] = f"{sym} Corp."
                results.append(r)

        cols = ["Ticker", "Company", "Price", "RS_Rank",
                "Pct_From_52W_High", "MA50", "MA150", "MA200",
                "52W_High", "52W_Low"]
        df = pd.DataFrame(results, columns=cols) if results else pd.DataFrame(columns=cols)

        html = generate_html(df, "2026-06-14 00:00 UTC")

        assert "<!DOCTYPE html>" in html
        assert "Minervini" in html
        assert len(html) > 2000

        # ファイルとして保存（確認用）
        with open("docs/test_report.html", "w", encoding="utf-8") as f:
            f.write(html)

        print(f"{PASS} HTML 生成: OK（{len(html):,} 文字）")
        print(f"  プレビュー: docs/test_report.html に保存")
        print(f"  通過銘柄数: {len(df)}")
        return True
    except Exception as e:
        print(f"{FAIL} エラー: {e}")
        traceback.print_exc()
        return False


# ────────────────────────────────────────────
# テスト 6: CSV 出力
# ────────────────────────────────────────────
def test_csv_output(close_map: dict, rs_ranks: dict):
    section("テスト 6: CSV 出力")
    try:
        import os
        from screening import screen_ticker

        results = []
        for sym, close in close_map.items():
            r = screen_ticker(sym, close, 85.0)
            if r:
                r["Company"] = f"{sym} Corp."
                results.append(r)

        cols = ["Ticker", "Company", "Price", "RS_Rank",
                "Pct_From_52W_High", "MA50", "MA150", "MA200",
                "52W_High", "52W_Low"]
        df = pd.DataFrame(results, columns=cols) if results else pd.DataFrame(columns=cols)

        os.makedirs("results", exist_ok=True)
        df.to_csv("results/test_output.csv", index=False)

        # 読み込み検証
        df2 = pd.read_csv("results/test_output.csv")
        assert list(df2.columns) == cols

        print(f"{PASS} CSV 出力: OK（{len(df2)} 行）")
        print(f"  保存先: results/test_output.csv")
        if not df2.empty:
            print(f"\n  出力内容:")
            print(df2[["Ticker", "Price", "RS_Rank", "Pct_From_52W_High"]].to_string(index=False))
        return True
    except Exception as e:
        print(f"{FAIL} エラー: {e}")
        traceback.print_exc()
        return False


# ────────────────────────────────────────────
# メイン
# ────────────────────────────────────────────
def main():
    print("=" * 50)
    print("  Minervini Screener コンポーネントテスト")
    print("=" * 50)

    results = {}

    # テスト 1
    ok1, ticker_count = test_ticker_fetch()
    results["1_ticker_fetch"] = ok1

    # テスト 2
    ok2, close_map = test_price_fetch()
    results["2_price_fetch"] = ok2

    if not ok2 or not close_map:
        print(f"\n{FAIL} 株価取得に失敗したため後続テストをスキップします")
        sys.exit(1)

    # テスト 3
    ok3, rs_ranks = test_rs_calculation(close_map)
    results["3_rs_calc"] = ok3

    # テスト 4
    ok4 = test_trend_template(close_map, rs_ranks)
    results["4_trend_template"] = ok4

    # テスト 5
    ok5 = test_html_generation(close_map, rs_ranks)
    results["5_html_gen"] = ok5

    # テスト 6
    ok6 = test_csv_output(close_map, rs_ranks)
    results["6_csv_output"] = ok6

    # サマリー
    section("テスト結果サマリー")
    labels = {
        "1_ticker_fetch":  "Nasdaq ティッカー取得",
        "2_price_fetch":   "yfinance 株価取得",
        "3_rs_calc":       "RS 計算・ランク化",
        "4_trend_template":"トレンドテンプレート 8 条件",
        "5_html_gen":      "HTML レポート生成",
        "6_csv_output":    "CSV 出力",
    }
    all_ok = True
    for key, ok in results.items():
        icon = PASS if ok else FAIL
        print(f"  {icon} {labels[key]}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print(f"{PASS} 全テスト通過! 本番実行 (python screening.py) が可能です。")
    else:
        print(f"{FAIL} 一部テストが失敗しました。上記のエラーを確認してください。")
        sys.exit(1)


if __name__ == "__main__":
    main()
