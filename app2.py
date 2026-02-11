import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime, timedelta, timezone

# ==========================================
# 設定 & ページ構成
# ==========================================
st.set_page_config(layout="wide", page_title="底打確認組")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}

JST = timezone(timedelta(hours=9))

# ==========================================
# CSS: フォント & デザイン設定
# ==========================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Shippori+Mincho+B1:wght@800&display=swap');

h1 {
    font-family: 'Genkai Mincho', 'Shippori Mincho B1', serif !important;
    font-weight: 800 !important;
    font-size: 3.5rem !important;
    text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
}
h3 {
    font-family: 'Hiragino Sans', 'Yu Gothic', sans-serif !important;
    color: gray;
    margin-top: -15px !important;
    font-size: 1.2rem !important;
}
/* 詳細表示（4本値）のスタイル */
div[data-testid="stMetric"] {
    background-color: #f8f9fa;
    padding: 10px;
    border-radius: 5px;
    border: 1px solid #e0e0e0;
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 関数: PDF表示用
# ==========================================
def display_pdf(url):
    viewer_url = f"https://docs.google.com/viewer?url={url}&embedded=true"
    st.markdown(
        f'<iframe src="{viewer_url}" width="100%" height="800" frameborder="0"></iframe>',
        unsafe_allow_html=True
    )

# ==========================================
# 関数: TDnetデータ取得
# ==========================================
@st.cache_data(ttl=300)
def get_tdnet_data(target_date):
    date_str = target_date.strftime('%Y%m%d')
    base_url = "https://www.release.tdnet.info/inbs/I_list_{}_{}.html"
    root_url = "https://www.release.tdnet.info/inbs/"
    disclosure_map = {}
    page = 1
    while True:
        url = base_url.format(f"{page:03}", date_str)
        try:
            res = requests.get(url, headers=HEADERS, timeout=5)
            if res.status_code == 404: break
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.select("table tr")
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    code_full = cols[1].text.strip()
                    code_4 = code_full[:4]
                    title = cols[3].text.strip()
                    link_tag = cols[3].find('a')
                    pdf_url = ""
                    if link_tag and 'href' in link_tag.attrs:
                        pdf_url = root_url + link_tag['href']
                    if code_4 not in disclosure_map: disclosure_map[code_4] = []
                    disclosure_map[code_4].append({"time": cols[0].text.strip(), "title": title, "url": pdf_url})
            page += 1
            time.sleep(0.1)
        except: break
    return disclosure_map

# ==========================================
# 関数: PTSランキング取得
# ==========================================
@st.cache_data(ttl=60)
def get_ranking_data(threshold, max_items):
    candidates = []
    seen_codes = set()
    targets = [
        ("https://kabutan.jp/warning/pts_night_price_increase", "急騰"),
        ("https://kabutan.jp/warning/pts_night_price_decrease", "急落")
    ]
    progress_text = "PTSデータを取得中..."
    my_bar = st.progress(0, text=progress_text)
    
    for base_url, label in targets:
        page = 1
        keep_fetching = True
        while keep_fetching:
            url = base_url if page == 1 else f"{base_url}?page={page}"
            if page > 20: break
            try:
                time.sleep(0.2)
                res = requests.get(url, headers=HEADERS, timeout=10)
                res.encoding = res.apparent_encoding 
                soup = BeautifulSoup(res.text, 'html.parser')
                table = soup.select_one("table.stock_table")
                if not table:
                    keep_fetching = False; continue
                tbody = table.find("tbody")
                rows = tbody.find_all("tr") if tbody else table.find_all("tr")[2:]
                if not rows:
                    keep_fetching = False; continue
                
                valid_count = 0
                for row in rows:
                    cols = row.find_all(["td", "th"])
                    if len(cols) < 10: continue
                    try:
                        pct_str = cols[8].text.strip()
                        clean_pct = pct_str.replace("%", "").replace("+", "").replace(",", "")
                        if not clean_pct: continue
                        change_pct = float(clean_pct)
                        if abs(change_pct) < threshold or change_pct == 0: continue
                        
                        code_tag = cols[0].find('a')
                        code = code_tag.text.strip() if code_tag else cols[0].text.strip()
                        if code in seen_codes: continue
                        seen_codes.add(code)
                        
                        name = cols[1].text.strip()
                        market = cols[2].text.strip()
                        pts_price_str = cols[6].text.strip()
                        pts_price = float(pts_price_str.replace(",", "")) if pts_price_str.replace(",", "").replace(".", "").isdigit() else 0
                        
                        candidates.append({
                            "Code": code, "Name": name, "Market": market,
                            "PTS_Price": pts_price, "Change_Pct": change_pct, "Label": label
                        })
                        valid_count += 1
                    except: continue
                if valid_count == 0: keep_fetching = False
                else:
                    page += 1
                    my_bar.progress(min(len(candidates), 100), text=f"{label} {page-1}ページ目... ({len(candidates)}件)")
                    if max_items > 0 and len(candidates) >= max_items * 2: keep_fetching = False
            except: keep_fetching = False
    my_bar.empty()
    return pd.DataFrame(candidates)

# ==========================================
# 関数: 日中4本値
# ==========================================
def get_daily_ohlc(code):
    url = f"https://kabutan.jp/stock/?code={code}"
    d = {"Open": "-", "High": "-", "Low": "-", "Close": "-"}
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        def find_val(label):
            th = soup.find("th", string=label)
            if th:
                td = th.find_next_sibling("td")
                if td: return td.text.strip()
            return "-"
        d["Open"] = find_val("始値"); d["High"] = find_val("高値")
        d["Low"] = find_val("安値"); d["Close"] = find_val("終値")
        if d["Close"] == "-":
            span = soup.select_one("span.kabuka")
            if span: d["Close"] = span.text.strip()
        return d
    except: return d

# ==========================================
# UI構築: サイドバー
# ==========================================
st.sidebar.header("🔍 検索条件設定")
search_date = st.sidebar.date_input("TDnet検索日", value=datetime.now(JST).date())
st.sidebar.subheader("PTS設定")
threshold_percent = st.sidebar.slider("変動率 閾値 (%)", 0.0, 20.0, 3.0, 0.1)
col_p1, col_p2 = st.sidebar.columns(2)
min_price = col_p1.number_input("下限 (円)", value=0, step=100)
max_price = col_p2.number_input("上限 (円)", value=0, step=100)
max_items = st.sidebar.number_input("検索上限数", value=0, step=10)

st.sidebar.divider()
if st.sidebar.button("データ更新 / リロード", type="primary"):
    st.cache_data.clear()
    st.rerun()

# ==========================================
# UI構築: メイン画面
# ==========================================
st.title("底打確認組")
st.subheader("PTS急動意 & 適時開示モニター")

# --- PTSデータ処理 ---
with st.spinner(f'{search_date.strftime("%Y/%m/%d")} のデータ収集中...'):
    tdnet_data = get_tdnet_data(search_date)
    df_pts = get_ranking_data(threshold_percent, max_items)

if not df_pts.empty:
    if min_price > 0: df_pts = df_pts[df_pts["PTS_Price"] >= min_price]
    if max_price > 0: df_pts = df_pts[df_pts["PTS_Price"] <= max_price]
    df_pts = df_pts.reindex(df_pts["Change_Pct"].abs().sort_values(ascending=False).index)
    if max_items > 0: df_pts = df_pts.head(max_items)

col_L, col_R = st.columns([1, 1])

with col_L:
    st.subheader("PTS ランキング")
    limit_txt = f"上位{max_items}件" if max_items > 0 else "全件"
    st.caption(f"閾値: ±{threshold_percent}% | 表示: {limit_txt} | Hits: {len(df_pts)}")
    
    if not df_pts.empty:
        df_pts["News"] = df_pts["Code"].apply(lambda x: "📄あり" if x in tdnet_data else "")
        show_df = df_pts[["Code", "Name", "Market", "PTS_Price", "Change_Pct", "News", "Label"]]
        
        event = st.dataframe(
            show_df.style.format({"Change_Pct": "{:.2f}%", "PTS_Price": "{:,.0f}"}).map(
                lambda x: 'color: red;' if x < 0 else 'color: green;', subset=['Change_Pct']
            ),
            use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", height=700
        )
        selected_rows = event.selection.rows
        sel_code = show_df.iloc[selected_rows[0]]["Code"] if selected_rows else None
        sel_name = show_df.iloc[selected_rows[0]]["Name"] if selected_rows else None
    else:
        st.warning("該当なし"); sel_code = None

with col_R:
    d_lbl = search_date.strftime("%Y/%m/%d")
    st.subheader(f"詳細 & 開示 ({d_lbl})")
    
    if sel_code:
        st.markdown(f"### {sel_code} {sel_name}")
        with st.spinner('詳細取得中...'): ohlc = get_daily_ohlc(sel_code)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("始値", ohlc["Open"]); c2.metric("高値", ohlc["High"])
        c3.metric("安値", ohlc["Low"]); c4.metric("終値", ohlc["Close"])
        st.divider()
        
        if sel_code in tdnet_data:
            news = tdnet_data[sel_code]
            st.success(f"開示: {len(news)} 件")
            tabs = st.tabs([f"{n['time']}" for n in news])
            for i, t in enumerate(tabs):
                with t:
                    st.markdown(f"**{news[i]['title']}**")
                    if news[i]['url']:
                        st.link_button("↗ PDFを開く", news[i]['url'])
                        display_pdf(news[i]['url'])
        else:
            st.info("開示なし")
            st.markdown(f"[Yahoo!掲示板](https://finance.yahoo.co.jp/quote/{sel_code}.T/bbs)")
    else:
        st.info("👈 銘柄を選択")