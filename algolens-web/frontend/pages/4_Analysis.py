import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Analysis | AlgoLens", page_icon="📊", layout="wide")
st.title("📊 提出分析")

BUCKET_ORDER = ["灰", "茶", "緑", "水", "青", "黄", "橙", "赤"]

DIFFICULTY_COLORS = {
    "灰": "#808080",
    "茶": "#804000",
    "緑": "#008000",
    "水": "#00C0C0",
    "青": "#0000FF",
    "黄": "#C0C000",
    "橙": "#FF8000",
    "赤": "#FF0000",
}


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

if st.sidebar.button("🔄 データを再取得"):
    st.rerun()

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
# DEBUG: APIレスポンスの生データ数を表示
# ============================================================
with st.expander("🐛 デバッグ情報（原因調査用）", expanded=True):
    diff_stats_raw = data.get("difficulty_stats", [])
    tag_stats_raw = data.get("tag_stats", [])

    st.markdown("**① APIから取得した直後のデータ数**")
    col_d1, col_d2, col_d3 = st.columns(3)
    col_d1.metric("DB内 総提出数", data["total_submissions"])
    col_d2.metric("difficulty_stats（全バケット数）", len(diff_stats_raw))
    col_d3.metric("tag_stats（全タグ種類数）", len(tag_stats_raw))

    st.markdown("**② difficulty_stats の内訳（グラフに渡す直前）**")
    if diff_stats_raw:
        import pandas as pd
        df_debug_diff = pd.DataFrame(diff_stats_raw)
        st.dataframe(df_debug_diff, use_container_width=True)
    else:
        st.warning("difficulty_stats が空です → 難易度データがDBに入っていない可能性があります。")

    st.markdown("**③ tag_stats 上位10件（グラフに渡す直前）**")
    if tag_stats_raw:
        df_debug_tag = pd.DataFrame(tag_stats_raw[:10])
        st.dataframe(df_debug_tag, use_container_width=True)
        st.caption(f"tag_stats 全 {len(tag_stats_raw)} 件のうち上位10件を表示")
    else:
        st.warning("tag_stats が空です → タグデータがDBに入っていない可能性があります。")

# ============================================================
# サマリー指標
# ============================================================
col1, col2, col3 = st.columns(3)
col1.metric("総提出数", data["total_submissions"])
col2.metric("AC 数", data["ac_count"])
col3.metric("AC 済み問題数（ユニーク）", data["unique_ac_problems"])

st.divider()

# ============================================================
# 難易度別グラフ（Plotly）
# ============================================================
diff_stats = data.get("difficulty_stats", [])
if diff_stats:
    df = pd.DataFrame(diff_stats)
    # API から返ってくる難易度帯だけを順序通りに並べる
    df["bucket"] = pd.Categorical(df["bucket"], categories=BUCKET_ORDER, ordered=True)
    df = df.sort_values("bucket").reset_index(drop=True)

    col_left, col_right = st.columns(2)

    # ── グラフ①: 難易度別 AC 問題数 ──────────────────────────
    with col_left:
        st.subheader("難易度別 AC 問題数")
        fig_ac = px.bar(
            df,
            x="bucket",
            y="ac_count",
            color="bucket",
            color_discrete_map=DIFFICULTY_COLORS,
            labels={"bucket": "難易度", "ac_count": "AC 問題数"},
            text="ac_count",
        )
        fig_ac.update_traces(textposition="outside")
        fig_ac.update_layout(
            showlegend=False,
            xaxis_title="難易度",
            yaxis_title="AC 問題数",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_ac, use_container_width=True)

    # ── グラフ②: 難易度帯ごとの正答率 ───────────────────────
    with col_right:
        st.subheader("難易度帯ごとの正答率")
        fig_rate = px.bar(
            df,
            x="bucket",
            y="ac_rate",
            color="bucket",
            color_discrete_map=DIFFICULTY_COLORS,
            labels={"bucket": "難易度", "ac_rate": "正答率"},
            text=df["ac_rate"].map("{:.0%}".format),
        )
        fig_rate.update_traces(textposition="outside")
        fig_rate.update_layout(
            showlegend=False,
            xaxis_title="難易度",
            yaxis_title="正答率",
            yaxis_tickformat=".0%",
            yaxis_range=[0, 1.15],
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_rate, use_container_width=True)

    # ── 詳細テーブル ─────────────────────────────────────────
    with st.expander("詳細テーブルを表示"):
        df_display = df[["bucket", "total", "ac_count", "ac_rate"]].copy()
        df_display.columns = ["難易度", "総提出", "AC 数", "正答率"]
        df_display["正答率"] = df_display["正答率"].map("{:.1%}".format)
        st.dataframe(df_display, use_container_width=True, hide_index=True)
else:
    st.info("難易度データがありません。AtCoder Problems API で難易度推定されていない問題のみ提出している場合も表示されません。")

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
