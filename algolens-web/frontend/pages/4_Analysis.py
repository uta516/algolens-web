import pandas as pd
import requests
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Analysis | AlgoLens", page_icon="📊", layout="wide")
st.title("📊 提出分析")

DIFFICULTY_COLORS = {
    "灰": "#808080",
    "茶": "#804000",
    "緑": "#008000",
    "水": "#00C0C0",
    "青": "#0000FF",
    "黄": "#C0C000",
    "橙": "#FF8000",
    "赤": "#FF0000",
    "不明": "#AAAAAA",
}


@st.cache_data(ttl=60)
def fetch_analysis(username: str):
    r = requests.get(f"{API_BASE}/analysis/{username}", timeout=10)
    if r.ok:
        return r.json()
    if r.status_code == 404:
        return None
    r.raise_for_status()


username = st.sidebar.text_input(
    "AtCoder ユーザー名",
    value=st.session_state.get("username", ""),
    placeholder="例: tourist",
)
if username:
    st.session_state["username"] = username

if not username:
    st.info("サイドバーにユーザー名を入力してください。")
    st.stop()

try:
    data = fetch_analysis(username)
except requests.exceptions.ConnectionError:
    st.error("バックエンドに接続できません。")
    st.stop()

if data is None:
    st.warning(f"ユーザー `{username}` が見つかりません。[Sync](/3_Sync) ページで同期してください。")
    st.stop()

# ============================================================
# サマリー指標
# ============================================================
col1, col2, col3 = st.columns(3)
col1.metric("総提出数", data["total_submissions"])
col2.metric("AC 数", data["ac_count"])
col3.metric("AC 済み問題数（ユニーク）", data["unique_ac_problems"])

st.divider()

# ============================================================
# 難易度別グラフ
# ============================================================
st.subheader("難易度別 提出状況")

diff_stats = data.get("difficulty_stats", [])
if diff_stats:
    df_diff = pd.DataFrame(diff_stats)
    df_diff["非AC"] = df_diff["total"] - df_diff["ac_count"]
    df_diff = df_diff.rename(columns={"bucket": "難易度", "ac_count": "AC", "total": "合計"})

    st.bar_chart(
        df_diff.set_index("難易度")[["AC", "非AC"]],
        use_container_width=True,
        color=["#4CAF50", "#F44336"],
    )

    df_diff_display = df_diff[["難易度", "合計", "AC"]].copy()
    df_diff_display["AC率"] = (df_diff["AC"] / df_diff["合計"]).map("{:.1%}".format)
    st.dataframe(df_diff_display, use_container_width=True, hide_index=True)
else:
    st.info("難易度データがありません。")

st.divider()

# ============================================================
# タグ別グラフ
# ============================================================
st.subheader("タグ別 提出状況")

tag_stats = data.get("tag_stats", [])
if tag_stats:
    df_tag = pd.DataFrame(tag_stats)
    df_tag["非AC"] = df_tag["total"] - df_tag["ac_count"]
    df_tag = df_tag.rename(columns={"tag": "タグ", "ac_count": "AC", "ac_rate": "AC率", "total": "合計"})

    top_n = st.slider("表示するタグ数（上位）", min_value=5, max_value=min(50, len(df_tag)), value=min(20, len(df_tag)))
    df_tag_top = df_tag.head(top_n)

    st.bar_chart(
        df_tag_top.set_index("タグ")[["AC", "非AC"]],
        use_container_width=True,
        color=["#4CAF50", "#F44336"],
    )

    df_tag_display = df_tag_top[["タグ", "合計", "AC", "AC率"]].copy()
    df_tag_display["AC率"] = df_tag_display["AC率"].map("{:.1%}".format)
    st.dataframe(df_tag_display, use_container_width=True, hide_index=True)
else:
    st.info("タグデータがありません。")
