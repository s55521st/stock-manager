import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import anthropic
import feedparser
import requests
import json
import os
import re
from email.utils import parsedate_to_datetime
from dotenv import load_dotenv, set_key

BASE_DIR = os.path.dirname(__file__)
PORTFOLIO_FILE = os.path.join(BASE_DIR, "portfolio.json")
ENV_FILE = os.path.join(BASE_DIR, ".env")

load_dotenv(ENV_FILE)

st.set_page_config(
    page_title="株式ポートフォリオ管理",
    page_icon="📈",
    layout="wide"
)

@st.cache_resource
def _get_supabase():
    try:
        from supabase import create_client
        try:
            url = st.secrets["SUPABASE_URL"]
            key = st.secrets["SUPABASE_ANON_KEY"]
        except Exception:
            url = os.environ.get("SUPABASE_URL", "")
            key = os.environ.get("SUPABASE_ANON_KEY", "")
        if url and key:
            return create_client(url, key)
    except ImportError:
        pass
    return None

def load_portfolio():
    sb = _get_supabase()
    if sb:
        try:
            res = sb.table("portfolio").select("data").eq("id", "main").single().execute()
            return res.data["data"]
        except Exception:
            return {"stocks": []}
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"stocks": []}

def save_portfolio(portfolio):
    sb = _get_supabase()
    if sb:
        try:
            sb.table("portfolio").upsert({"id": "main", "data": portfolio}).execute()
            return
        except Exception:
            pass
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)

@st.cache_data(ttl=0)
def _load_jp_stocks():
    path = os.path.join(BASE_DIR, "jp_stocks.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _has_japanese(text):
    return any("　" <= c <= "鿿" or "＀" <= c <= "￯" for c in text)

def _is_crypto(ticker):
    parts = ticker.upper().split("-")
    return len(parts) == 2 and parts[1] in ("USD", "JPY", "EUR", "GBP", "USDT", "BTC")

_CRYPTO_LIST = [
    {"symbol": "BTC-USD",  "longname": "ビットコイン",       "shortname": "Bitcoin",  "keywords": ["btc", "bitcoin", "ビットコイン"]},
    {"symbol": "ETH-USD",  "longname": "イーサリアム",       "shortname": "Ethereum", "keywords": ["eth", "ethereum", "イーサリアム"]},
    {"symbol": "SOL-USD",  "longname": "ソラナ",             "shortname": "Solana",   "keywords": ["sol", "solana", "ソラナ"]},
    {"symbol": "XRP-USD",  "longname": "リップル",           "shortname": "XRP",      "keywords": ["xrp", "ripple", "リップル"]},
    {"symbol": "BNB-USD",  "longname": "バイナンスコイン",   "shortname": "BNB",      "keywords": ["bnb", "binance", "バイナンス"]},
    {"symbol": "DOGE-USD", "longname": "ドージコイン",       "shortname": "Dogecoin", "keywords": ["doge", "dogecoin", "ドージ"]},
    {"symbol": "ADA-USD",  "longname": "カルダノ",           "shortname": "Cardano",  "keywords": ["ada", "cardano", "カルダノ"]},
    {"symbol": "AVAX-USD", "longname": "アバランチ",         "shortname": "Avalanche","keywords": ["avax", "avalanche", "アバランチ"]},
]

def _search_crypto(query):
    q = query.lower().strip()
    results = []
    for c in _CRYPTO_LIST:
        if q in c["symbol"].lower() or any(q in kw for kw in c["keywords"]):
            results.append({
                "symbol": c["symbol"],
                "longname": c["longname"],
                "shortname": c["shortname"],
                "quoteType": "CRYPTOCURRENCY",
                "exchDisp": "Crypto",
            })
    return results

def _search_jp_stocks(query):
    q = query.lower().strip()
    pat_word = re.compile(r'(?<![a-z0-9])' + re.escape(q) + r'(?![a-z0-9])', re.I)
    exact, word_match, substr = [], [], []
    seen = set()

    def make_entry(stock):
        return {
            "symbol": stock["symbol"],
            "longname": stock["longname"],
            "shortname": stock["shortname"],
            "quoteType": "EQUITY",
            "exchDisp": "東証",
        }

    for stock in _load_jp_stocks():
        if stock["symbol"] in seen:
            continue
        kws = [kw.lower() for kw in stock.get("keywords", [])]
        if q == stock["symbol"].lower():
            seen.add(stock["symbol"])
            exact.append(make_entry(stock))
        elif any(q == kw for kw in kws):
            seen.add(stock["symbol"])
            exact.append(make_entry(stock))
        elif any(pat_word.search(kw) for kw in kws):
            seen.add(stock["symbol"])
            word_match.append(make_entry(stock))
        elif any(q in kw for kw in kws):
            seen.add(stock["symbol"])
            substr.append(make_entry(stock))

    return (exact + word_match + substr)[:10]

@st.cache_data(ttl=300)
def search_stocks(query):
    # 暗号資産ローカル辞書
    crypto = _search_crypto(query)
    if crypto:
        return crypto

    # 日本株ローカル辞書
    local = _search_jp_stocks(query)
    if local:
        return local

    # ヒットなしの場合のみ Yahoo Finance API へフォールバック
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    params = {
        "q": query,
        "lang": "ja",
        "region": "JP",
        "quotesCount": 10,
        "newsCount": 0,
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        quotes = resp.json().get("quotes", [])
        return [q for q in quotes if q.get("quoteType") in ("EQUITY", "ETF", "FUND", "CRYPTOCURRENCY")]
    except Exception:
        return []

def get_stock_info(ticker):
    try:
        return yf.Ticker(ticker).info
    except Exception:
        return {}

def get_stock_history(ticker):
    try:
        return yf.Ticker(ticker).history(period="max")
    except Exception:
        return None

def create_chart(ticker, hist):
    hist = hist.copy()
    hist["MA25"] = hist["Close"].rolling(25).mean()
    hist["MA75"] = hist["Close"].rolling(75).mean()

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.7, 0.3]
    )

    fig.add_trace(go.Candlestick(
        x=hist.index,
        open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"],
        name="株価",
        increasing_line_color="red",
        decreasing_line_color="blue"
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=hist.index, y=hist["MA25"],
        line=dict(color="orange", width=1),
        name="25日MA"
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=hist.index, y=hist["MA75"],
        line=dict(color="purple", width=1),
        name="75日MA"
    ), row=1, col=1)

    colors = [
        "red" if c >= o else "blue"
        for c, o in zip(hist["Close"], hist["Open"])
    ]
    fig.add_trace(go.Bar(
        x=hist.index, y=hist["Volume"],
        marker_color=colors,
        name="出来高",
        showlegend=False
    ), row=2, col=1)

    fig.update_layout(
        height=620,
        xaxis_rangeslider_visible=False,
        title=f"{ticker}　全期間チャート",
        legend=dict(orientation="h", y=1.02),
        xaxis=dict(title="日付"),
    )
    fig.update_yaxes(title_text="株価", row=1, col=1)
    fig.update_yaxes(title_text="出来高", row=2, col=1)
    return fig

def get_ai_analysis(ticker, hist, info, api_key, purchase_price=None):
    current_price = hist["Close"].iloc[-1]
    ma25 = hist["Close"].rolling(25).mean().iloc[-1]
    ma75 = hist["Close"].rolling(75).mean().iloc[-1]
    high_52w = hist["Close"].tail(252).max()
    low_52w = hist["Close"].tail(252).min()
    change_1m = (hist["Close"].iloc[-1] / hist["Close"].iloc[-21] - 1) * 100 if len(hist) > 21 else 0
    change_3m = (hist["Close"].iloc[-1] / hist["Close"].iloc[-63] - 1) * 100 if len(hist) > 63 else 0

    prompt = f"""あなたは経験豊富な株式アナリストです。以下のデータを基に銘柄分析を行ってください。

銘柄: {ticker}
会社名: {info.get('longName', ticker)}
業種: {info.get('sector', '不明')} / {info.get('industry', '不明')}

【価格情報】
現在値: {current_price:.2f}
25日移動平均: {ma25:.2f}（現在値との乖離: {(current_price/ma25-1)*100:+.1f}%）
75日移動平均: {ma75:.2f}（現在値との乖離: {(current_price/ma75-1)*100:+.1f}%）
52週高値: {high_52w:.2f}（高値からの下落率: {(current_price/high_52w-1)*100:.1f}%）
52週安値: {low_52w:.2f}（安値からの上昇率: {(current_price/low_52w-1)*100:+.1f}%）
1ヶ月騰落率: {change_1m:+.1f}%
3ヶ月騰落率: {change_3m:+.1f}%
"""
    if purchase_price and purchase_price > 0:
        pl_pct = (current_price - purchase_price) / purchase_price * 100
        prompt += f"\n【保有情報】\n購入価格: {purchase_price:.2f}（現在{pl_pct:+.1f}%）\n"

    prompt += """
以下の形式で日本語で分析してください：

## 📊 現在のトレンド分析
（移動平均線の位置関係、トレンドの方向性）

## 🟢 買い時の判断
（具体的な価格帯、条件、エントリーのタイミング）

## 🔴 売り時の判断
（利益確定・損切りの目安価格、条件）

## ⚠️ リスク要因
（注意すべきリスク）

## 💡 総合判断
**強気 / 中立 / 弱気** のいずれかを明示し、理由を簡潔に述べてください。

---
※本分析は教育目的です。投資の最終判断はご自身の責任でお願いします。"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

@st.cache_data(ttl=300)
def get_portfolio_summary(ticker_keys):
    """全銘柄の現在値・評価額・損益をまとめて取得する (ticker_keys はキャッシュキー用タプル)"""
    import pandas as pd
    usdjpy = get_usdjpy_rate()
    rows = []
    for ticker, name, qty, purchase_price in ticker_keys:
        hist = get_stock_history(ticker)
        if hist is None or hist.empty:
            continue
        close   = hist["Close"].dropna()
        current = float(close.iloc[-1])
        prev    = float(close.iloc[-2]) if len(close) > 1 else current
        is_jpy  = ticker.endswith(".T")
        rate    = 1.0 if is_jpy else usdjpy
        value   = current * qty * rate
        cost    = purchase_price * qty * rate if purchase_price > 0 else None
        pl      = (value - cost) if cost is not None else None
        pl_pct  = ((current - purchase_price) / purchase_price * 100) if purchase_price > 0 else None
        day_chg = (current - prev) / prev * 100
        rows.append(dict(
            ticker=ticker, name=name, qty=qty,
            current=current, is_jpy=is_jpy,
            value=value, cost=cost, pl=pl, pl_pct=pl_pct,
            day_chg=day_chg,
        ))
    return rows, usdjpy

@st.cache_data(ttl=1800)
def get_usdjpy_rate():
    try:
        return float(yf.Ticker("USDJPY=X").history(period="5d")["Close"].iloc[-1])
    except Exception:
        return 150.0

def get_portfolio_forecast(stocks, api_key):
    usdjpy = get_usdjpy_rate()
    summaries = []
    total_current_jpy = 0

    for stock in stocks:
        qty = stock["quantity"]
        hist = get_stock_history(stock["ticker"])
        if hist is None or hist.empty:
            continue
        current = float(hist["Close"].iloc[-1])
        ma25    = float(hist["Close"].rolling(25).mean().iloc[-1])
        ma75    = float(hist["Close"].rolling(75).mean().iloc[-1])
        high52  = float(hist["Close"].tail(252).max())
        low52   = float(hist["Close"].tail(252).min())
        chg1m   = (current / hist["Close"].iloc[-21] - 1) * 100 if len(hist) > 21 else 0
        chg3m   = (current / hist["Close"].iloc[-63] - 1) * 100 if len(hist) > 63 else 0
        is_jpy  = stock["ticker"].endswith(".T")
        val_jpy = current * qty if is_jpy else current * qty * usdjpy
        total_current_jpy += val_jpy
        ccy = "円" if is_jpy else "ドル"
        summaries.append({
            "ticker": stock["ticker"], "name": stock["name"],
            "quantity": qty, "current_price": current, "is_jpy": is_jpy,
            "val_jpy": val_jpy, "ccy": ccy,
            "ma25": ma25, "ma75": ma75, "high52": high52, "low52": low52,
            "chg1m": chg1m, "chg3m": chg3m,
        })

    if not summaries:
        return None

    lines = "\n".join(
        f"- {s['name']}（{s['ticker']}）: 保有{s['quantity']}株, "
        f"現在{s['current_price']:.2f}{s['ccy']}, "
        f"25日MA {s['ma25']:.2f}, 75日MA {s['ma75']:.2f}, "
        f"52週高値 {s['high52']:.2f} / 安値 {s['low52']:.2f}, "
        f"1ヶ月騰落率 {s['chg1m']:+.1f}%, 3ヶ月騰落率 {s['chg3m']:+.1f}%"
        for s in summaries
    )

    prompt = f"""あなたは経験豊富な株式アナリストです。以下のポートフォリオを分析し、今後の価格予測を行ってください。

現在のドル円レート: {usdjpy:.1f}円

【保有銘柄】
{lines}

各銘柄について、弱気・基本・強気の3シナリオで1ヶ月後・3ヶ月後・6ヶ月後・1年後の**株価変化率（%）**を予測してください。

以下のJSON形式のみで回答してください（前後に説明文不要）：
{{
  "forecasts": [
    {{
      "ticker": "ティッカー",
      "bear": {{"1m": -5.0, "3m": -10.0, "6m": -15.0, "1y": -20.0}},
      "base": {{"1m": 3.0, "3m":  7.0, "6m":  12.0, "1y":  18.0}},
      "bull": {{"1m": 8.0, "3m": 18.0, "6m":  30.0, "1y":  45.0}}
    }}
  ],
  "commentary": "ポートフォリオ全体の見通しと主なリスク要因を2〜3文で"
}}"""

    client = anthropic.Anthropic(api_key=api_key)
    text = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    ).content[0].text.strip()

    start = text.find("{")
    end   = text.rfind("}") + 1
    data  = json.loads(text[start:end])

    fc_map = {f["ticker"]: f for f in data["forecasts"]}
    horizons = ["1m", "3m", "6m", "1y"]
    totals = {sc: {} for sc in ("bear", "base", "bull")}

    for h in horizons:
        for sc in ("bear", "base", "bull"):
            total = 0
            for s in summaries:
                fc = fc_map.get(s["ticker"])
                chg = (fc[sc][h] / 100) if fc else 0
                future_price = s["current_price"] * (1 + chg)
                total += future_price * s["quantity"] if s["is_jpy"] else future_price * s["quantity"] * usdjpy
            totals[sc][h] = total

    return {
        "current": total_current_jpy,
        "totals": totals,
        "commentary": data.get("commentary", ""),
        "summaries": summaries,
        "usdjpy": usdjpy,
    }

def get_news(ticker, company_name=""):
    query = company_name if company_name else ticker.replace(".T", "")
    url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        feed = feedparser.parse(url)
        return feed.entries[:10]
    except Exception:
        return []

APPLE_CSS = """
<style>
/* ── Global typography ── */
html, body, [class*="css"], .stMarkdown, .stMetric {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",
                 "SF Pro Text", "Helvetica Neue", Arial, sans-serif !important;
}
/* ── Hide Streamlit chrome ── */
#MainMenu, footer, header { visibility: hidden; }
/* ── Page title ── */
.apple-title {
    font-size: 2.4rem; font-weight: 700; color: #f5f5f7;
    letter-spacing: -0.5px; margin-bottom: 4px;
}
/* ── Section header ── */
.apple-section {
    font-size: 1.5rem; font-weight: 700; color: #f5f5f7;
    letter-spacing: -0.3px; margin: 28px 0 14px;
}
/* ── Metric card ── */
.apple-metric {
    background: #1c1c1e;
    border-radius: 18px;
    padding: 20px 22px;
    border: 1px solid #2c2c2e;
    height: 100%;
    margin-bottom: 10px;
}
.apple-metric .label {
    font-size: 0.78rem; font-weight: 500;
    color: #636366; text-transform: uppercase; letter-spacing: 0.5px;
    margin-bottom: 8px;
}
.apple-metric .value {
    font-size: 1.9rem; font-weight: 700; color: #f5f5f7; line-height: 1.1;
}
.apple-metric .sub {
    font-size: 0.88rem; font-weight: 500; margin-top: 4px;
}
/* ── Stock card ── */
.stock-card {
    background: #1c1c1e;
    border-radius: 18px;
    padding: 18px 22px;
    margin-bottom: 10px;
    border: 1px solid #2c2c2e;
    display: flex;
    align-items: center;
    gap: 0;
}
.stock-card:hover { border-color: #3a3a3c; }
.sc-name  { font-size: 1.15rem; font-weight: 700; color: #f5f5f7; line-height: 1.2; }
.sc-sub   { font-size: 0.78rem; color: #636366; margin-top: 3px; font-family: "SF Mono", monospace; }
.sc-val   { font-size: 1.25rem; font-weight: 600; color: #f5f5f7; }
.sc-label { font-size: 0.75rem; color: #636366; margin-top: 2px; }
.up   { color: #30d158; }
.down { color: #ff453a; }
/* ── Divider ── */
.apple-divider { border:none; border-top: 1px solid #2c2c2e; margin: 8px 0 18px; }
/* ── Stock card buttons (portfolio list) ── */
[data-testid="stMarkdown"]:has(.portfolio-list-start) ~ [data-testid="stButton"] > button {
    background: #1c1c1e !important;
    border: 1px solid #2c2c2e !important;
    border-radius: 18px !important;
    padding: 18px 22px !important;
    text-align: left !important;
    color: #f5f5f7 !important;
    height: auto !important;
    white-space: pre-line !important;
    line-height: 1.85 !important;
    font-size: 0.95rem !important;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif !important;
    font-weight: 400 !important;
    width: 100% !important;
    margin-bottom: 4px !important;
    letter-spacing: -0.1px !important;
}
[data-testid="stMarkdown"]:has(.portfolio-list-start) ~ [data-testid="stButton"] > button:hover {
    border-color: #0071e3 !important;
    background: #2c2c2e !important;
}
[data-testid="stMarkdown"]:has(.portfolio-list-start) ~ [data-testid="stButton"] > button p {
    margin: 0 !important;
    padding: 0 !important;
    line-height: 1.85 !important;
    text-align: left !important;
    color: inherit !important;
}
[data-testid="stMarkdown"]:has(.portfolio-list-start) ~ [data-testid="stButton"] > button p:first-child {
    font-size: 1.05rem !important;
    font-weight: 700 !important;
    color: #f5f5f7 !important;
}
[data-testid="stMarkdown"]:has(.portfolio-list-start) ~ [data-testid="stButton"] > button p:nth-child(2) {
    font-size: 0.88rem !important;
    color: #c0c0c5 !important;
}
[data-testid="stMarkdown"]:has(.portfolio-list-start) ~ [data-testid="stButton"] > button p:nth-child(3) {
    font-size: 0.85rem !important;
    color: #a1a1a6 !important;
}
/* ── Tab bar ── */
.stButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;
    transition: all 0.15s !important;
}

/* ════════════════════════════════
   モバイル (〜768px)
   ════════════════════════════════ */
@media (max-width: 768px) {
    /* タイトル */
    .apple-title { font-size: 1.5rem !important; }
    .apple-section { font-size: 1.1rem !important; margin: 16px 0 10px !important; }
    [data-testid="stHeading"] h2,
    [data-testid="stHeading"] h3 { font-size: 1.1rem !important; }

    /* メトリクスカード: 縦並び時の余白 */
    .apple-metric { padding: 12px 14px !important; margin-bottom: 10px !important; }
    .apple-metric .value { font-size: 1.2rem !important; }
    .apple-metric .label { font-size: 0.65rem !important; }
    .apple-metric .sub { font-size: 0.75rem !important; }

    /* Stock card buttons on mobile */
    [data-testid="stMarkdown"]:has(.portfolio-list-start) ~ [data-testid="stButton"] > button {
        padding: 14px 16px !important;
        line-height: 1.75 !important;
        font-size: 0.88rem !important;
    }

    /* タブボタン: タップしやすく */
    .stButton > button { min-height: 48px !important; font-size: 0.9rem !important; }
}
</style>
"""

def main():
    st.markdown(APPLE_CSS, unsafe_allow_html=True)
    st.markdown('<div class="apple-title">📈 株式ポートフォリオ管理</div>', unsafe_allow_html=True)

    if "portfolio" not in st.session_state:
        st.session_state.portfolio = load_portfolio()
    if "form_key" not in st.session_state:
        st.session_state.form_key = 0
    if "active_tab" not in st.session_state:
        st.session_state.active_tab = "portfolio"
    if "selected_stock_idx" not in st.session_state:
        st.session_state.selected_stock_idx = 0

    stocks = st.session_state.portfolio["stocks"]
    if stocks:
        st.session_state.selected_stock_idx = min(
            st.session_state.selected_stock_idx, len(stocks) - 1
        )

    with st.sidebar:
        st.header("⚙️ 設定")

        if "api_key" not in st.session_state:
            try:
                saved_key = st.secrets.get("ANTHROPIC_API_KEY", "")
            except Exception:
                saved_key = ""
            if not saved_key:
                saved_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if saved_key:
                st.session_state.api_key = saved_key

        has_saved_key = bool(st.session_state.get("api_key"))
        if has_saved_key:
            st.success("APIキー: 保存済み ✓")
            if st.button("キーを変更する", use_container_width=True):
                st.session_state.show_key_input = True
        else:
            st.session_state.show_key_input = True

        if st.session_state.get("show_key_input"):
            api_key = st.text_input(
                "Anthropic APIキー",
                type="password",
                placeholder="sk-ant-...",
                help="入力すると自動保存されます"
            )
            if api_key:
                st.session_state.api_key = api_key
                set_key(ENV_FILE, "ANTHROPIC_API_KEY", api_key)
                st.session_state.show_key_input = False
                st.success("保存しました")
                st.rerun()

        st.divider()
        st.header("📋 ポートフォリオ")

        fk = st.session_state.form_key
        with st.expander("＋ 銘柄を追加"):
            search_q = st.text_input(
                "🔍 銘柄を検索",
                placeholder="会社名 または ティッカー（例: トヨタ、AAPL）",
                key=f"search_q_{fk}",
            )

            selected_result = None
            if search_q and len(search_q) >= 1:
                with st.spinner("検索中..."):
                    results = search_stocks(search_q)

                if results:
                    search_options = ["── 選択してください ──"] + [
                        f"{r['symbol']}　{(r.get('longname') or r.get('shortname', ''))[:16]}　[{r.get('exchDisp', '')}]"
                        for r in results
                    ]
                    choice_idx = st.selectbox(
                        "検索結果",
                        range(len(search_options)),
                        format_func=lambda i: search_options[i],
                        key=f"choice_{fk}",
                    )
                    if choice_idx > 0:
                        selected_result = results[choice_idx - 1]
                else:
                    st.caption("該当する銘柄が見つかりませんでした")

            ticker_default = selected_result["symbol"] if selected_result else ""
            new_ticker = st.text_input(
                "ティッカー（直接入力も可）",
                value=ticker_default,
                placeholder="例: 7203.T / AAPL / BTC-USD",
                key=f"ticker_{fk}",
            )
            _t_detect = (new_ticker or ticker_default).strip().upper()
            is_jpy_add    = _t_detect.endswith(".T")
            is_crypto_add = _is_crypto(_t_detect)
            if is_crypto_add:
                new_qty = st.number_input(
                    "保有数量（枚）", min_value=0.0, value=0.0, step=0.0001,
                    format="%.6f", key=f"qty_{fk}"
                )
            else:
                new_qty = st.number_input("保有数量（株）", min_value=0, value=100, step=1, key=f"qty_{fk}")
            if is_jpy_add:
                new_price = float(st.number_input(
                    "購入価格（円）", min_value=0, value=0, step=1,
                    help="0のままでも追加できます", key=f"price_{fk}",
                ))
            elif is_crypto_add:
                new_price = st.number_input(
                    "購入価格（ドル）", min_value=0.0, value=0.0, step=100.0,
                    help="0のままでも追加できます", key=f"price_{fk}",
                )
            else:
                new_price = st.number_input(
                    "購入価格（ドル）", min_value=0.0, value=0.0, step=0.01,
                    help="0のままでも追加できます", key=f"price_{fk}",
                )
            if st.button("追加する", type="primary", use_container_width=True, key=f"add_{fk}"):
                final_ticker = new_ticker.strip().upper() if new_ticker else ticker_default
                if final_ticker:
                    existing = [s["ticker"] for s in st.session_state.portfolio["stocks"]]
                    if final_ticker in existing:
                        st.warning(f"「{final_ticker}」はすでに登録されています")
                    else:
                        if selected_result and selected_result["symbol"] == final_ticker:
                            name = selected_result.get("longname") or selected_result.get("shortname") or final_ticker
                        else:
                            with st.spinner("銘柄情報を取得中..."):
                                info = get_stock_info(final_ticker)
                            name = info.get("longName") or info.get("shortName") or final_ticker
                        entry = {
                            "ticker": final_ticker,
                            "name": name,
                            "quantity": new_qty,
                            "purchase_price": new_price
                        }
                        st.session_state.portfolio["stocks"].append(entry)
                        save_portfolio(st.session_state.portfolio)
                        st.session_state.form_key += 1
                        st.rerun()
                else:
                    st.warning("銘柄を検索または直接入力してください")

        st.divider()

        if stocks:
            sidebar_options = [f"{s['ticker']}  {s['name'][:12]}" for s in stocks]
            new_sidebar_idx = st.radio(
                "銘柄を選択",
                range(len(sidebar_options)),
                index=st.session_state.selected_stock_idx,
                format_func=lambda i: sidebar_options[i]
            )
            if new_sidebar_idx != st.session_state.selected_stock_idx:
                st.session_state.selected_stock_idx = new_sidebar_idx
                st.session_state.active_tab = "stock"
                st.rerun()
        else:
            st.info("銘柄を追加してください")

    # ── カスタムタブバー ──
    _tc1, _tc2 = st.columns(2)
    with _tc1:
        if st.button(
            "📊 ポートフォリオ",
            use_container_width=True,
            type="primary" if st.session_state.active_tab == "portfolio" else "secondary",
            key="tab_btn_portfolio"
        ):
            st.session_state.active_tab = "portfolio"
            st.rerun()
    with _tc2:
        if st.button(
            "📈 個別銘柄",
            use_container_width=True,
            type="primary" if st.session_state.active_tab == "stock" else "secondary",
            key="tab_btn_stock"
        ):
            st.session_state.active_tab = "stock"
            st.rerun()

    # ══ ポートフォリオタブ ══
    if st.session_state.active_tab == "portfolio":
        if not stocks:
            st.markdown("""
### 👋 ようこそ

左のサイドバーから銘柄を追加してください。

**ティッカーの入力例**
| 銘柄 | ティッカー |
|---|---|
| トヨタ自動車 | `7203.T` |
| ソニーグループ | `6758.T` |
| 任天堂 | `7974.T` |
| Apple | `AAPL` |
| NVIDIA | `NVDA` |
| Microsoft | `MSFT` |

> 日本株は証券コードの末尾に `.T` をつけます
""")
        else:
            st.subheader("📊 ポートフォリオ ダッシュボード")

            ticker_keys = tuple(
                (s["ticker"], s["name"], s["quantity"], s["purchase_price"])
                for s in stocks
            )
            with st.spinner("データを取得中..."):
                rows, usdjpy = get_portfolio_summary(ticker_keys)

            if rows:
                total_value = sum(r["value"] for r in rows)
                total_pl    = sum(r["pl"] for r in rows if r["pl"] is not None)
                has_pl      = any(r["pl"] is not None for r in rows)
                total_day   = sum(r["value"] * r["day_chg"] / 100 for r in rows)
                day_pct     = total_day / total_value * 100 if total_value else 0
                day_cls     = "up" if total_day >= 0 else "down"
                day_sign    = "+" if total_day >= 0 else ""
                pl_cls      = "up" if total_pl >= 0 else "down"

                total_cost = sum(r["cost"] for r in rows if r["cost"] is not None)
                has_cost   = any(r["cost"] is not None for r in rows)

                c1, c2, c3, c4, c5 = st.columns(5)
                c1.markdown(f"""
<div class="apple-metric">
  <div class="label">合計評価額</div>
  <div class="value">¥{total_value:,.0f}</div>
</div>""", unsafe_allow_html=True)
                c2.markdown(f"""
<div class="apple-metric">
  <div class="label">前日比（概算）</div>
  <div class="value {day_cls}">{day_sign}¥{total_day:,.0f}</div>
  <div class="sub {day_cls}">{day_sign}{day_pct:.2f}%</div>
</div>""", unsafe_allow_html=True)
                if has_pl:
                    pl_pct_total = total_pl / (total_value - total_pl) * 100 if (total_value - total_pl) else 0
                    c3.markdown(f"""
<div class="apple-metric">
  <div class="label">含み損益合計</div>
  <div class="value {pl_cls}">¥{total_pl:+,.0f}</div>
  <div class="sub {pl_cls}">{pl_pct_total:+.2f}%</div>
</div>""", unsafe_allow_html=True)
                else:
                    c3.markdown("""
<div class="apple-metric">
  <div class="label">含み損益合計</div>
  <div class="value" style="color:#636366">—</div>
</div>""", unsafe_allow_html=True)
                if has_cost:
                    c4.markdown(f"""
<div class="apple-metric">
  <div class="label">投資金額</div>
  <div class="value">¥{total_cost:,.0f}</div>
  <div class="sub" style="color:#636366">取得原価</div>
</div>""", unsafe_allow_html=True)
                else:
                    c4.markdown("""
<div class="apple-metric">
  <div class="label">投資金額</div>
  <div class="value" style="color:#636366">—</div>
</div>""", unsafe_allow_html=True)
                c5.markdown(f"""
<div class="apple-metric">
  <div class="label">保有銘柄数</div>
  <div class="value">{len(rows)}</div>
  <div class="sub" style="color:#636366">銘柄</div>
</div>""", unsafe_allow_html=True)

                st.markdown('<div class="apple-section">保有株一覧</div>', unsafe_allow_html=True)
                st.markdown('<div class="portfolio-list-start"></div>', unsafe_allow_html=True)

                for r in rows:
                    if r["is_jpy"]:
                        price_str = f"¥{r['current']:,.0f}"
                    elif _is_crypto(r["ticker"]):
                        price_str = f"¥{r['current'] * usdjpy:,.0f}（${r['current']:,.0f}）"
                    else:
                        price_str = f"¥{r['current'] * usdjpy:,.0f}"
                    value_str = f"¥{r['value']:,.0f}"
                    if r["day_chg"] >= 0:
                        d_chg = f":green[▲ {abs(r['day_chg']):.2f}%]"
                    else:
                        d_chg = f":red[▼ {abs(r['day_chg']):.2f}%]"

                    _name = r['name'].split(' - ')[0].strip()
                    if len(_name) > 18:
                        _name = _name[:18] + "…"
                    line1 = _name
                    if _is_crypto(r['ticker']):
                        qty_str = f"×{r['qty']:g}枚"
                    else:
                        qty_str = f"×{int(r['qty']):,}株"
                    line2 = f"{r['ticker']}    {price_str}  {qty_str}    {d_chg}"
                    if r["pl"] is not None:
                        pl_str = f"¥{r['pl']:+,.0f}（{r['pl_pct']:+.2f}%）"
                        pl_colored = f":green[{pl_str}]" if r["pl"] >= 0 else f":red[{pl_str}]"
                        line3 = f"評価額 {value_str}    損益 {pl_colored}"
                    else:
                        line3 = f"評価額 {value_str}"

                    label = f"{line1}\n\n{line2}\n\n{line3}"
                    _stock_idx = next(
                        (i for i, s in enumerate(stocks) if s["ticker"] == r["ticker"]), 0
                    )
                    if st.button(label, key=f"card_{r['ticker']}", use_container_width=True):
                        st.session_state.selected_stock_idx = _stock_idx
                        st.session_state.active_tab = "stock"
                        st.rerun()

                st.markdown(
                    f'<div style="font-size:0.75rem;color:#636366;margin-top:12px">'
                    f'USD/JPY: {usdjpy:.1f}円　※ 前日比は終値ベースの概算</div>',
                    unsafe_allow_html=True
                )

            st.subheader("🤖 ポートフォリオ AI将来予測")

            has_key = bool(st.session_state.get("api_key"))
            if not has_key:
                st.warning("サイドバーでAnthropicのAPIキーを入力してください")
            else:
                if st.button("🤖 AI予測を生成する", type="primary"):
                    with st.spinner("Claudeが各銘柄を分析中です...（20〜40秒ほどかかります）"):
                        try:
                            result = get_portfolio_forecast(stocks, st.session_state.api_key)
                            st.session_state["portfolio_forecast"] = result
                        except Exception as e:
                            st.error(f"エラーが発生しました: {e}")

                if "portfolio_forecast" in st.session_state:
                    r = st.session_state["portfolio_forecast"]
                    current = r["current"]
                    totals  = r["totals"]

                    import datetime
                    today = datetime.date.today()
                    x_dates = [
                        today,
                        today + datetime.timedelta(days=30),
                        today + datetime.timedelta(days=91),
                        today + datetime.timedelta(days=182),
                        today + datetime.timedelta(days=365),
                    ]
                    horizons = ["1m", "3m", "6m", "1y"]

                    bear_y = [current] + [totals["bear"][h] for h in horizons]
                    base_y = [current] + [totals["base"][h] for h in horizons]
                    bull_y = [current] + [totals["bull"][h] for h in horizons]

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("現在の評価額", f"¥{current:,.0f}")
                    c2.metric("基本シナリオ 1年後", f"¥{totals['base']['1y']:,.0f}",
                              f"{(totals['base']['1y']/current-1)*100:+.1f}%")
                    c3.metric("強気シナリオ 1年後", f"¥{totals['bull']['1y']:,.0f}",
                              f"{(totals['bull']['1y']/current-1)*100:+.1f}%")
                    c4.metric("弱気シナリオ 1年後", f"¥{totals['bear']['1y']:,.0f}",
                              f"{(totals['bear']['1y']/current-1)*100:+.1f}%")

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=x_dates + x_dates[::-1],
                        y=bull_y + bear_y[::-1],
                        fill="toself",
                        fillcolor="rgba(100,160,255,0.15)",
                        line=dict(color="rgba(0,0,0,0)"),
                        name="予測レンジ",
                        hoverinfo="skip",
                    ))
                    fig.add_trace(go.Scatter(
                        x=x_dates, y=bear_y, mode="lines+markers",
                        line=dict(color="#3b82f6", width=2, dash="dot"),
                        marker=dict(size=7), name="弱気シナリオ",
                        hovertemplate="%{x|%Y/%m/%d}<br>¥%{y:,.0f}<extra>弱気</extra>",
                    ))
                    fig.add_trace(go.Scatter(
                        x=x_dates, y=base_y, mode="lines+markers",
                        line=dict(color="#10b981", width=3),
                        marker=dict(size=9), name="基本シナリオ",
                        hovertemplate="%{x|%Y/%m/%d}<br>¥%{y:,.0f}<extra>基本</extra>",
                    ))
                    fig.add_trace(go.Scatter(
                        x=x_dates, y=bull_y, mode="lines+markers",
                        line=dict(color="#f59e0b", width=2, dash="dot"),
                        marker=dict(size=7), name="強気シナリオ",
                        hovertemplate="%{x|%Y/%m/%d}<br>¥%{y:,.0f}<extra>強気</extra>",
                    ))
                    fig.add_hline(
                        y=current, line_dash="dash", line_color="gray",
                        annotation_text="現在", annotation_position="left",
                    )
                    fig.update_layout(
                        height=480,
                        xaxis=dict(title="日付", tickformat="%Y/%m"),
                        yaxis=dict(title="評価額（円）", tickformat=",.0f"),
                        hovermode="x unified",
                        legend=dict(orientation="h", y=1.05),
                        margin=dict(l=0, r=0, t=30, b=0),
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    if r["commentary"]:
                        st.info(f"💬 **AI総評**: {r['commentary']}")

                    st.caption("※ この予測はAIによる試算です。実際の投資判断はご自身の責任でお願いします。")

    # ══ 個別銘柄タブ ══
    elif st.session_state.active_tab == "stock":
        if not stocks:
            st.info("左のサイドバーから銘柄を追加してください")
        else:
            selected_idx = st.session_state.selected_stock_idx
            stock = stocks[selected_idx]
            ticker = stock["ticker"]

            col_title, col_refresh, col_delete = st.columns([4, 1, 1])
            with col_title:
                st.subheader(f"{stock['name']}　（{ticker}）")
            with col_refresh:
                if st.button("🔄 更新", use_container_width=True):
                    st.rerun()
            with col_delete:
                if st.button("🗑️ 削除", use_container_width=True):
                    st.session_state.portfolio["stocks"].pop(selected_idx)
                    save_portfolio(st.session_state.portfolio)
                    st.session_state.selected_stock_idx = max(0, selected_idx - 1)
                    st.session_state.active_tab = "portfolio"
                    st.rerun()

            with st.spinner("データを取得中..."):
                hist = get_stock_history(ticker)
                info = get_stock_info(ticker)

            if hist is None or hist.empty:
                st.error(f"「{ticker}」のデータを取得できませんでした。ティッカーを確認してください。")
            else:
                close = hist["Close"].dropna()
                current_price = float(close.iloc[-1])
                prev_price = float(close.iloc[-2]) if len(close) > 1 else current_price
                change = current_price - prev_price
                change_pct = change / prev_price * 100
                is_jpy = ticker.endswith(".T")

                # 円/ドル切り替え（米国株・暗号資産のみ表示）
                if not is_jpy:
                    _usdjpy_disp = get_usdjpy_rate()
                    _col_tog, _ = st.columns([2, 8])
                    with _col_tog:
                        show_jpy = st.toggle("💴 円表示", value=True, key=f"show_jpy_{ticker}")
                    disp_rate = _usdjpy_disp if show_jpy else 1.0
                    disp_jpy  = show_jpy
                else:
                    disp_rate = 1.0
                    disp_jpy  = True

                def fmt_price(p):
                    if disp_jpy:
                        return f"¥{p * disp_rate:,.0f}"
                    return f"${p:,.2f}"

                def fmt_chg(p):
                    if disp_jpy:
                        return f"¥{p * disp_rate:+,.0f}  ({change_pct:+.2f}%)"
                    return f"${p:+.2f}  ({change_pct:+.2f}%)"

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("現在値", fmt_price(current_price), fmt_chg(change))

                _is_cr = _is_crypto(ticker)
                _qty_unit = "枚" if _is_cr else "株"
                _qty_disp = f"{stock['quantity']:g}" if _is_cr else f"{int(stock['quantity']):,}"
                c2.metric("保有コイン数" if _is_cr else "保有数量", f"{_qty_disp} {_qty_unit}")

                if _is_cr:
                    _val = current_price * stock["quantity"]
                    _val_str = f"¥{_val * disp_rate:,.0f}" if disp_jpy else f"${_val:,.2f}"
                    c3.metric("評価額", _val_str)
                    if stock["purchase_price"] > 0:
                        pl = (current_price - stock["purchase_price"]) * stock["quantity"]
                        pl_pct = (current_price - stock["purchase_price"]) / stock["purchase_price"] * 100
                        pl_disp = f"¥{pl * disp_rate:+,.0f}" if disp_jpy else f"${pl:+,.2f}"
                        c4.metric("評価損益", pl_disp, f"{pl_pct:+.2f}%")
                    else:
                        c4.metric("52週安値", fmt_price(hist["Close"].tail(252).min()))
                else:
                    if stock["purchase_price"] > 0:
                        pl = (current_price - stock["purchase_price"]) * stock["quantity"]
                        pl_pct = (current_price - stock["purchase_price"]) / stock["purchase_price"] * 100
                        c3.metric("購入価格", fmt_price(stock["purchase_price"]))
                        pl_disp = f"¥{pl * disp_rate:+,.0f}" if disp_jpy else f"${pl:+,.2f}"
                        c4.metric("評価損益", pl_disp, f"{pl_pct:+.2f}%")
                    else:
                        c3.metric("52週高値", fmt_price(hist["Close"].tail(252).max()))
                        c4.metric("52週安値", fmt_price(hist["Close"].tail(252).min()))

                inner1, inner2, inner3 = st.tabs(["📊 チャート", "🤖 AI考察", "📰 ニュース"])

                with inner1:
                    fig = create_chart(ticker, hist)
                    st.plotly_chart(fig, use_container_width=True)

                with inner2:
                    has_key = hasattr(st.session_state, "api_key") and st.session_state.api_key
                    if not has_key:
                        st.warning("サイドバーでAnthropicのAPIキーを入力してください")
                    else:
                        if st.button("🤖 AI考察を生成する", type="primary"):
                            with st.spinner("Claudeが分析中です...（10〜20秒ほどかかります）"):
                                try:
                                    analysis = get_ai_analysis(
                                        ticker, hist, info,
                                        st.session_state.api_key,
                                        stock["purchase_price"]
                                    )
                                    st.session_state[f"analysis_{ticker}"] = analysis
                                except Exception as e:
                                    st.error(f"エラーが発生しました: {e}")
                        if f"analysis_{ticker}" in st.session_state:
                            st.markdown(st.session_state[f"analysis_{ticker}"])

                with inner3:
                    with st.spinner("ニュースを取得中..."):
                        news = get_news(ticker, stock["name"])
                    if news:
                        for entry in news:
                            title = entry.get("title", "タイトルなし")
                            link = entry.get("link", "")
                            published = entry.get("published", "")
                            summary = entry.get("summary", "")
                            st.markdown(f"**[{title}]({link})**")
                            if published:
                                try:
                                    dt = parsedate_to_datetime(published)
                                    st.caption(dt.strftime("%Y年%m月%d日 %H:%M"))
                                except Exception:
                                    st.caption(published)
                            if summary:
                                st.markdown(f"<small>{summary[:200]}</small>", unsafe_allow_html=True)
                            st.divider()
                    else:
                        st.info("ニュースが見つかりませんでした")


if __name__ == "__main__":
    main()
