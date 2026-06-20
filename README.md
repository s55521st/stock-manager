# 📈 ポートフォリオ管理アプリ

株式・暗号資産のポートフォリオを管理するWebアプリ。スマートフォン・PCどちらからでもアクセス可能。

---

## 🌐 アクセス

| 項目 | URL / 情報 |
|---|---|
| アプリ本体 | https://share.streamlit.io → `s55521st/stock-manager` |
| GitHubリポジトリ | https://github.com/s55521st/stock-manager |

---

## 🛠 使用技術

| 役割 | 技術 |
|---|---|
| 言語 | Python 3 |
| UIフレームワーク | [Streamlit](https://streamlit.io/) |
| グラフ | Plotly |
| 株価・暗号資産データ | [yfinance](https://github.com/ranaroussi/yfinance)（Yahoo Finance経由） |
| AI分析 | [Anthropic Claude API](https://console.anthropic.com/)（claude-sonnet-4-6） |
| ニュース | Google News RSS |

---

## 🗄 データベース（Supabase）

ポートフォリオデータ（保有銘柄・数量・購入価格）をクラウドに保存。

| 項目 | 情報 |
|---|---|
| サービス | [Supabase](https://supabase.com/) |
| プラン | Free |
| テーブル名 | `portfolio` |
| 構造 | `id: "main"`, `data: JSON`（1行にまとめて保存） |
| RLS | 無効（`ALTER TABLE portfolio DISABLE ROW LEVEL SECURITY;`） |

### Supabase の確認・操作

1. https://supabase.com → プロジェクトを開く
2. **Table Editor** → `portfolio` テーブルでデータ確認・編集
3. **SQL Editor** でクエリ実行可能

---

## 🚀 デプロイ（Streamlit Community Cloud）

| 項目 | 情報 |
|---|---|
| サービス | [Streamlit Community Cloud](https://share.streamlit.io/) |
| プラン | 無料 |
| リポジトリ | `s55521st/stock-manager`（**Public 必須**） |
| メインファイル | `app.py` |
| 自動デプロイ | `main` ブランチに push すると自動で再デプロイ |

### デプロイ手順（初回・再設定時）

1. https://share.streamlit.io にログイン
2. **New app** → GitHub リポジトリ `s55521st/stock-manager` を選択
3. Main file: `app.py` を指定
4. **Secrets** に以下を設定（↓参照）
5. **Deploy**

---

## 🔑 Secrets（環境変数）

Streamlit Cloud の **App Settings → Secrets** に設定。

```toml
SUPABASE_URL = "https://xxxxxxxxxxxx.supabase.co"
SUPABASE_ANON_KEY = "eyJ..."
ANTHROPIC_API_KEY = "sk-ant-..."
```

| キー | 取得場所 |
|---|---|
| `SUPABASE_URL` | Supabase → Project Settings → API → Project URL |
| `SUPABASE_ANON_KEY` | Supabase → Project Settings → API → anon public |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → API Keys |

> **ローカル開発時** は `.env` ファイルに同じキーを書けば動作する（`.gitignore` 済み）

---

## 📁 ファイル構成

```
stock-manager/
├── app.py                  # メインアプリ
├── requirements.txt        # Python 依存パッケージ
├── jp_stocks.json          # 日本株銘柄辞書（検索用）
├── .streamlit/
│   └── config.toml         # テーマ設定（ダークモード）
├── .env                    # ローカル用 API キー（.gitignore 済み）
└── .gitignore
```

---

## 🔄 コードの更新方法

```bash
# 変更して push するだけで自動デプロイ
cd ~/stock-manager
git add app.py
git commit -m "変更内容"
git push origin main
```

push 後 1〜2分で Streamlit Cloud に反映される。

---

## 📦 対応銘柄

| 種別 | 入力形式 | 例 |
|---|---|---|
| 日本株 | `証券コード.T` | `7203.T`（トヨタ） |
| 米国株 | ティッカー | `NVDA`, `AAPL` |
| 暗号資産 | `コイン-USD` | `BTC-USD`, `ETH-USD` |

---

## ⚠️ 注意事項

- **Supabase Free プラン**：一定期間アクセスがないとプロジェクトが停止する。再開は Supabase ダッシュボードから
- **yfinance**：Yahoo Finance の仕様変更でデータ取得が失敗することがある
- **Anthropic API**：AI 分析・予測機能の利用には API キーと利用料金が必要
- **Streamlit Cloud**：無料プランはリソース制限あり。長時間使わないとスリープする場合がある
