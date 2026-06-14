# 📈 Minervini Trend Template Screener

マーク・ミネルヴィニの「トレンドテンプレート」を用いた米国株スクリーニングを毎日自動実行するシステムです。  
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
| **毎日自動実行** | GitHub Actions で JST 火〜土 8:00 に自動実行（PCは不要） |
| **スマホ対応レポート** | ダークテーマ・ソート機能付きの HTML レポートを GitHub Pages で公開 |
| **CSV 出力** | 日付付き CSV と最新版 `latest.csv` を `results/` に保存 |

---

## 📁 ファイル構成

```
.
├── .github/
│   └── workflows/
│       └── main.yml          # GitHub Actions ワークフロー
├── docs/
│   └── index.html            # スマホ対応 HTML レポート（自動生成）
├── results/
│   ├── latest.csv            # 最新スクリーニング結果
│   └── screening_YYYYMMDD.csv
├── screening.py              # メインスクリプト
├── requirements.txt
└── README.md
```

---

## 🔍 スクリーニング条件（トレンドテンプレート）

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

## ⏰ 自動実行スケジュール

| 実行日時（JST） | 対象市場日 |
|----------------|-----------|
| 火曜 08:00 | 月曜引け後 |
| 水曜 08:00 | 火曜引け後 |
| 木曜 08:00 | 水曜引け後 |
| 金曜 08:00 | 木曜引け後 |
| 土曜 08:00 | 金曜引け後 |

---

## 📊 出力 CSV のカラム

| カラム | 説明 |
|--------|------|
| `Ticker` | ティッカーシンボル |
| `Company` | 企業名 |
| `Price` | 現在株価（USD） |
| `RS_Rank` | RS パーセンタイルランク（0〜100） |
| `Pct_From_52W_High` | 52 週高値からの下落率（%） |
| `MA50` | 50 日移動平均 |
| `MA150` | 150 日移動平均 |
| `MA200` | 200 日移動平均 |
| `52W_High` | 52 週高値 |
| `52W_Low` | 52 週安値 |

---

## 🛠️ ローカルで実行する場合

```bash
pip install -r requirements.txt
python screening.py
```

結果は `results/` と `docs/index.html` に出力されます。

---

## ⚠️ 注意事項

- **実行時間**: 全米株（約 5,000〜7,000 銘柄）を対象にするため 30〜90 分かかります
- **GitHub Actions 無料枠**: 月 2,000 分。週 5 日 × 約 60 分 = 月約 1,200 分で無料枠内に収まります
- **データソース**: yfinance（Yahoo Finance）を使用。上場廃止やデータ欠損の銘柄は自動スキップされます
- **投資判断**: 本ツールはスクリーニング補助目的です。投資は自己責任でお願いします

---

## 📚 参考

- [Mark Minervini - Trend Template](https://www.minervini.com/)
- [yfinance ドキュメント](https://ranaroussi.github.io/yfinance/)
- [Nasdaq Trader Symbol Directory](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs)
