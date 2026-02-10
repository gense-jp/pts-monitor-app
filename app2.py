import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime

# ==========================================
# 設定
# ==========================================
st.set_page_config(layout="wide", page_title="PTS & TDnet Monitor")
THRESHOLD_PERCENT = 3.0
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}

# ==========================================
# 関数: PDF表示用 (Google Docs Viewer経由)
# ==========================================
def display_pdf(url):
    """
    Google Docs Viewerを使用してPDFを表示する
    (TDnetのiframeブロックやMixed Contentエラーを回避するため)
    """
    # Googleのビューアを経由させるURLを作成
    viewer_url = f"https://docs.google.com/viewer?url={url}&embedded=true"
    
    # iframeで表示
    st.markdown(
        f'<iframe src="{viewer_url}" width="100%" height="800" frameborder="0"></iframe>',
        unsafe_allow_html=True
    )

# ==========================================
# 関数: TDnetデータ取得
# ==========================================
@st.cache_data(ttl=300)
def get_todays_tdnet_data():
    date_str = datetime.now().strftime('%Y%m%d')
    base_url = "https://www.release.tdnet.info/inbs/I_list_{}_{}.html"
    root_url = "https://www.release.tdnet.info/inbs/"
    
    disclosure_map = {}
    page = 1
    
    while True:
        url = base_url.format(f"{page:03}", date_str)
        try:
            res = requests.get(url, headers=HEADERS, timeout=5)
            if res.status_code == 404: break
            
            res.encoding = 'utf-8' # 文字化け対策
            
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
                    
                    if code_4 not in disclosure_map:
                        disclosure_map[code_4] = []
                    
                    disclosure_map[code_4].append({
                        "time": cols[0].text.strip(),
                        "title": title,
                        "url": pdf_url
                    })
            page += 1
            time.sleep(0.1)
        except: break
    return disclosure_map

# ==========================================
# 関数: PTSランキング取得
# ==========================================
@st.cache_data(ttl=60)
def get_ranking_data():
    candidates = []
    targets = [
        ("https://kabutan.jp/warning/pts_night_price_increase", "急騰"),
        ("https://kabutan.jp/warning/pts_night_price_decrease", "急落")
    ]
    
    progress_text = "PTSデータを取得中..."
    my_bar = st.progress(0, text=progress_text)
    
    for url, label in targets:
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            res.encoding = res.apparent_encoding 
            
            soup = BeautifulSoup(res.text, 'html.parser')
            table = soup.select_one("table.stock_table")
            if not table: continue
            
            tbody = table.find("tbody")
            if tbody:
                rows = tbody.find_all("tr")
            else:
                rows = table.find_all("tr")[2:]
            
            for row in rows:
                cols = row.find_all(["td", "th"])
                if len(cols) < 10: continue
                
                try:
                    pct_str = cols[8].text.strip()
                    clean_pct = pct_str.replace("%", "").replace("+", "").replace(",", "")
                    if not clean_pct: continue
                    change_pct = float(clean_pct)
                    
                    if abs(change_pct) >= THRESHOLD_PERCENT:
                        code_tag = cols[0].find('a')
                        code = code_tag.text.strip() if code_tag else cols[0].text.strip()
                        name = cols[1].text.strip()
                        pts_price = cols[6].text.strip()
                        
                        candidates.append({
                            "Code": code,
                            "Name": name,
                            "PTS_Price": pts_price,
                            "Change_Pct": change_pct,
                            "Label": label
                        })
                except: continue
        except: continue
        
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

        d["Open"] = find_val("始値")
        d["High"] = find_val("高値")
        d["Low"] = find_val("安値")
        d["Close"] = find_val("終値")
        if d["Close"] == "-":
            span = soup.select_one("span.kabuka")
            if span: d["Close"] = span.text.strip()
        return d
    except: return d


# ==========================================
# メイン画面
# ==========================================
st.title("📊 PTS急動意 & 適時開示モニター")

with st.spinner('データ収集中...'):
    tdnet_data = get_todays_tdnet_data()
    df_pts = get_ranking_data()

col_left, col_right = st.columns([1, 1]) 

with col_left:
    st.subheader("PTS ランキング (±3%以上)")
    
    if not df_pts.empty:
        df_pts["News"] = df_pts["Code"].apply(lambda x: "📄あり" if x in tdnet_data else "")
        display_df = df_pts[["Code", "Name", "PTS_Price", "Change_Pct", "News", "Label"]]
        
        event = st.dataframe(
            display_df.style.format({"Change_Pct": "{:.2f}%"}).map(
                lambda x: 'color: red;' if x < 0 else 'color: green;', subset=['Change_Pct']
            ),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            height=600
        )
        
        selected_rows = event.selection.rows
        if selected_rows:
            idx = selected_rows[0]
            selected_code = display_df.iloc[idx]["Code"]
            selected_name = display_df.iloc[idx]["Name"]
        else:
            selected_code = None
    else:
        st.info("条件に一致する銘柄はありません。")
        selected_code = None

with col_right:
    st.subheader("詳細 & 適時開示プレビュー")
    
    if selected_code:
        st.markdown(f"### {selected_code} {selected_name}")
        
        with st.spinner('株価詳細を取得中...'):
            ohlc = get_daily_ohlc(selected_code)
            
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("始値", ohlc["Open"])
        c2.metric("高値", ohlc["High"])
        c3.metric("安値", ohlc["Low"])
        c4.metric("終値", ohlc["Close"])
        
        st.divider()

        if selected_code in tdnet_data:
            news_list = tdnet_data[selected_code]
            st.success(f"本日 {len(news_list)} 件の開示があります")
            
            tabs = st.tabs([f"{n['time']} {n['title'][:10]}..." for n in news_list])
            
            for i, tab in enumerate(tabs):
                news = news_list[i]
                with tab:
                    st.markdown(f"**{news['title']}**")
                    if news['url']:
                        st.link_button("↗ 別タブでPDFを開く", news['url'])
                        display_pdf(news['url']) # Google Viewerで表示
                    else:
                        st.warning("PDFリンクがありません")
        else:
            st.info("本日の適時開示はありません。")
            st.markdown(f"• [Yahoo!掲示板](https://finance.yahoo.co.jp/quote/{selected_code}.T/bbs)")
    else:
        st.info("👈 左側の表から銘柄を選択してください")

st.divider()
if st.button("データ更新"):
    st.cache_data.clear()
    st.rerun()