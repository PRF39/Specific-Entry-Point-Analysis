# 📈 Minervini Trend Template Screener + 52週新高値セクター分析

マーク・ミネルヴィニの「トレンドテンプレート」を用いた米国株スクリーニングと、強気相場の初期にリーダーとなるセクターを特定する52週新高値分析を毎日自動実行するシステムです。  
GitHub Actions で完全自動化し、結果は GitHub Pages でスマホからも確認できます。

---

## 🖥️ デモ（GitHub Pages）

```
https://<あなたのユーザー名>.github.io/<リポジトリ名>/
```

スマホのホーム画面に追加するとアプリのように使えます。

---

## ✨ 機能

| 機能 | 内容 |
|------|------|
| **銘柄取得** | Nasdaq 公式リストから全米株を自動取得・フィルタリング |
| **RS 計算** | Minervini 式のレラティブストレングス（RS）をパーセンタイルランク化 |
| **8 条件スクリーニング** | トレンドテンプレートの全条件を自動チェック |
| **52週新高値セクター分析** | 高値更新銘柄が集中するセクターを自動ランキング |
| **毎日自動実行** | GitHub Actions で JST 火〜土 8:00 に自動実行（PCは不要） |
| **スマホ対応レポート** | ダークテーマ・ソート機能付きの HTML レポートを GitHub Pages で公開 |
| **CSV 出力** | 日付付き CSV と最新版を `results/` に保存 |

---

## 📁 ファイル構成

```
.
├── .github/
│   └── workflows/
│       └── main.yml                  # GitHub Actions ワークフロー
├── docs/
│   ├── index.html                    # トレンドテンプレート結果（自動生成）
│   └── new_highs_sector.html         # 52週新高値セクター分析（自動生成）
├── results/
│   ├── latest.csv                    # 最新トレンドテンプレート結果
│   ├── screening_YYYYMMDD.csv
│   ├── new_highs_sector.csv          # 最新セクター集計
│   ├── new_highs_stocks.csv          # 最新高値近接銘柄リスト
│   └── sector_cache.json             # セクター情報キャッシュ
├── screening.py                      # トレンドテンプレート スクリーニング
├── new_highs_sector.py               # 52週新高値セクター分析
├── requirements.txt
└── README.md
```

---

## 🔍 スクリーニング 1: トレンドテンプレート（`screening.py`）

以下の **8 条件をすべて満たす** 銘柄のみが通過します。

| # | 条件 |
|---|------|
| 1 | 株価 > MA150 かつ 株価 > MA200 |
| 2 | MA150 > MA200 |
| 3 | MA200 が 20 営業日前より上昇している |
| 4 | MA50 > MA150 かつ MA50 > MA200 |
| 5 | 株価 > MA50 |
| 6 | 株価が 52 週安値から +30% 以上 |
| 7 | 株価が 52 週高値から −25% 以内 |
| 8 | RS ランクが 80 以上（上位 20%） |

### RS 計算式

```
RS = ( (C-C63)/C63 × 0.4 + (C-C126)/C126 × 0.2
      + (C-C189)/C189 × 0.2 + (C-C252)/C252 × 0.2 ) × 100
```

`C` = 直近終値、`C63/C126/C189/C252` = 各営業日前の終値  
全銘柄で比較し、パーセンタイルランク（上位 1% ≈ 99）に変換します。

---

## 📊 スクリーニング 2: 52週新高値セクター分析（`new_highs_sector.py`）

強気相場の初期には、リーダーセクターが他セクターに先行して52週新高値を更新する銘柄を増やしていきます。  
このスクリプトは全米株の中から高値圏にある銘柄を特定し、セクター別に集計してランキングします。

### 判定ティア

| ティア | 条件 | 意味 |
|--------|------|------|
| **新高値** | 52週高値の **1% 以内** | ほぼ高値更新状態 |
| **高値近接** | 52週高値の **5% 以内** | 高値を意識した水準 |

### セクター出力（`new_highs_sector.csv`）

| カラム | 説明 |
|--------|------|
| `Sector` | セクター名 |
| `AT_High_Count` | 新高値（1%以内）の銘柄数 |
| `Near_High_Count` | 高値近接（5%以内）の銘柄数 |
| `Avg_Pct_From_High` | セクター内の平均高値乖離率（%） |
| `Top_Tickers` | 高値に最も近い上位5銘柄 |

### 個別銘柄出力（`new_highs_stocks.csv`）

| カラム | 説明 |
|--------|------|
| `Ticker` | ティッカーシンボル |
| `Price` | 現在株価（USD） |
| `52W_High` | 52週高値 |
| `Pct_From_52W_High` | 52週高値からの乖離率（%） |
| `Sector` | セクター名 |

### セクターキャッシュ

セクター情報は `results/sector_cache.json` にキャッシュされます。  
キャッシュを強制更新する場合は `--refresh-cache` オプションを使用してください。

```bash
python new_highs_sector.py --refresh-cache
```

---

## 🚀 セットアップ

### 1. リポジトリを作成してプッシュ

```bash
git init
git remote add origin https://github.com/<ユーザー名>/<リポジトリ名>.git
git add .
git commit -m "feat: initial setup"
git push -u origin main
```

### 2. GitHub Pages を有効化

1. リポジトリの **Settings → Pages**
2. Source: `Deploy from a branch`
3. Branch: `main` / Folder: `/docs`
4. **Save**

数分後に GitHub Pages URL でアクセス可能になります。

### 3. 初回動作確認（手動実行）

1. **Actions** タブ → **Daily Stock Screening**
2. **Run workflow** をクリック
3. 30〜90 分で完了後、GitHub Pages で結果を確認

---

## 🛠️ ローカルで実行する場合

```bash
pip install -r requirements.txt

# トレンドテンプレート
python screening.py

# 52週新高値セクター分析
python new_highs_sector.py
```

結果は `results/` と `docs/` に出力されます。

---

## ⏰ 自動実行スケジュール

| 実行日時（JST） | 対象市場日 |
|----------------|-----------|
| 火曜 08:00 | 月曜引け後 |
| 水曜 08:00 | 火曜引け後 |
| 木曜 08:00 | 水曜引け後 |
| 金曜 08:00 | 木曜引け後 |
| 土曜 08:00 | 金曜引け後 |

---

## ⚠️ 注意事項

- **実行時間**: 全米株（約 5,000〜7,000 銘柄）を対象にするため 30〜90 分かかります
- **GitHub Actions 無料枠**: 月 2,000 分。週 5 日 × 約 90 分 = 月約 1,800 分（無料枠内）
- **データソース**: yfinance（Yahoo Finance）を使用。上場廃止やデータ欠損の銘柄は自動スキップされます
- **投資判断**: 本ツールはスクリーニング補助目的です。投資は自己責任でお願いします

---

## 📚 参考

- [Mark Minervini - Trend Template](https://www.minervini.com/)
- [yfinance ドキュメント](https://ranaroussi.github.io/yfinance/)
- [Nasdaq Trader Symbol Directory](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs)
