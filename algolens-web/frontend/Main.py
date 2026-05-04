import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_BASE = "http://localhost:8000"

DIFF_COLORS = {
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

st.set_page_config(page_title="AlgoLens", page_icon="🔍", layout="wide")
st.title("🔍 AlgoLens Dashboard")
st.caption("AtCoder の提出データを分析し、弱点を可視化します。")

username = st.sidebar.text_input(
    "AtCoder ユーザー名",
    value=st.session_state.get("username", ""),
    placeholder="例: tourist",
)
if username:
    st.session_state["username"] = username

if not username:
    st.info("サイドバーに AtCoder ユーザー名を入力してください。")
    st.stop()


@st.cache_data(ttl=300)
def fetch_analysis(uname: str):
    return requests.get(f"{API_BASE}/analysis/{uname}", timeout=10)


try:
    resp = fetch_analysis(username)
except requests.exceptions.ConnectionError:
    st.error("バックエンドに接続できません。`start.ps1` でサーバーを起動してください。")
    st.stop()

if resp.status_code == 404:
    st.warning(f"ユーザー **{username}** が見つかりません。[Sync](/3_Sync) ページで登録してください。")
    st.stop()
elif resp.status_code != 200:
    st.error(f"API エラー: {resp.status_code}")
    st.stop()

data = resp.json()

# --- KPI ---
col1, col2, col3 = st.columns(3)
col1.metric("総提出数", f"{data['total_submissions']:,}")
col2.metric("AC 提出数", f"{data['ac_count']:,}")
col3.metric("ユニーク AC 問題数", f"{data['unique_ac_problems']:,}")

st.divider()

left, right = st.columns(2)

# --- 難易度別チャート ---
with left:
    st.subheader("難易度別 AC 状況")
    diff_stats = data["difficulty_stats"]
    if diff_stats:
        df_diff = pd.DataFrame(diff_stats)
        df_diff["非AC"] = df_diff["total"] - df_diff["ac_count"]
        df_diff = df_diff.rename(columns={"ac_count": "AC"})
        fig = px.bar(
            df_diff,
            x="bucket",
            y=["AC", "非AC"],
            color_discrete_map={"AC": "#22CC66", "非AC": "#FF6666"},
            labels={"value": "提出数", "bucket": "難易度", "variable": ""},
        )
        fig.update_layout(barmode="stack", margin=dict(t=20))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("難易度データがありません。")

# --- タグ別 AC 率チャート ---
with right:
    st.subheader("タグ別 AC 率（上位 15）")
    tag_stats = data["tag_stats"][:15]
    if tag_stats:
        df_tag = pd.DataFrame(tag_stats).sort_values("ac_rate")
        fig2 = px.bar(
            df_tag,
            x="ac_rate",
            y="tag",
            orientation="h",
            color="ac_rate",
            color_continuous_scale="RdYlGn",
            range_color=[0, 1],
            text=df_tag["ac_rate"].map(lambda v: f"{v:.0%}"),
            labels={"ac_rate": "AC 率", "tag": "タグ"},
        )
        fig2.update_traces(textposition="outside")
        fig2.update_coloraxes(showscale=False)
        fig2.update_layout(margin=dict(t=20))
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("タグデータがありません。")

# --- 弱点サマリー ---
if tag_stats:
    st.divider()
    st.subheader("🎯 弱点アルゴリズム（AC 率が低いタグ上位 5）")
    weak = sorted(tag_stats, key=lambda x: x["ac_rate"])[:5]
    for item in weak:
        ac_pct = item["ac_rate"] * 100
        label = "🔴" if ac_pct < 50 else "🟠"
        st.markdown(
            f"- {label} **{item['tag']}** — AC率 {ac_pct:.1f}%（{item['ac_count']}/{item['total']} 問）"
        )
