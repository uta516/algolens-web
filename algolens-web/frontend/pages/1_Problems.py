import pandas as pd
import requests
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Problems | AlgoLens", page_icon="📋", layout="wide")
st.title("📋 問題一覧 & 提出記録")

STATUS_ICONS = {
    "AC": "🟢",
    "WA": "🔴",
    "TLE": "🟡",
    "MLE": "🟠",
    "RE": "🟣",
    "CE": "⚫",
}


def fetch_problems(contest_id: str, limit: int):
    params = {"limit": limit}
    if contest_id:
        params["contest_id"] = contest_id.lower()
    r = requests.get(f"{API_BASE}/problems/", params=params, timeout=10)
    return r.json() if r.ok else []


def fetch_submissions(user_id: int | None, status: str, limit: int):
    params = {"limit": limit}
    if user_id:
        params["user_id"] = user_id
    if status:
        params["status"] = status
    r = requests.get(f"{API_BASE}/submissions/", params=params, timeout=10)
    return r.json() if r.ok else []


def get_user_id(username: str) -> int | None:
    r = requests.get(f"{API_BASE}/users/{username}", timeout=10)
    return r.json().get("id") if r.ok else None


# サイドバー: ユーザー名
username = st.sidebar.text_input(
    "AtCoder ユーザー名",
    value=st.session_state.get("username", ""),
    placeholder="例: tourist",
)
if username:
    st.session_state["username"] = username

if st.sidebar.button("🔄 データを再取得"):
    st.rerun()

tab_problems, tab_submissions = st.tabs(["問題一覧", "提出記録"])

# ============================================================
# Tab 1: 問題一覧
# ============================================================
with tab_problems:
    col_f1, col_f2 = st.columns([2, 1])
    with col_f1:
        contest_filter = st.text_input("コンテスト ID でフィルター", placeholder="例: abc300")
    with col_f2:
        prob_limit = st.number_input("取得件数", min_value=10, max_value=500, value=100, step=10)

    try:
        problems = fetch_problems(contest_filter, int(prob_limit))
    except requests.exceptions.ConnectionError:
        st.error("バックエンドに接続できません。")
        problems = []

    if problems:
        df = pd.DataFrame(problems)
        df["difficulty"] = df["difficulty"].apply(lambda x: int(x) if x is not None else None)
        df = df.rename(columns={
            "atcoder_problem_id": "問題 ID",
            "contest_id": "コンテスト",
            "problem_index": "番号",
            "title": "タイトル",
            "difficulty": "難易度",
            "tags": "タグ",
            "url": "URL",
        })
        st.caption(f"{len(df)} 件")
        st.dataframe(
            df[["問題 ID", "コンテスト", "番号", "タイトル", "難易度", "タグ", "URL"]],
            use_container_width=True,
            column_config={"URL": st.column_config.LinkColumn("URL", display_text="開く")},
            hide_index=True,
        )
    else:
        st.info("問題データがありません。[Sync](/3_Sync) ページで問題を同期してください。")

# ============================================================
# Tab 2: 提出記録
# ============================================================
with tab_submissions:
    col_s1, col_s2 = st.columns([1, 1])
    with col_s1:
        status_filter = st.selectbox(
            "ステータス",
            options=["（すべて）", "AC", "WA", "TLE", "MLE", "RE", "CE"],
        )
    with col_s2:
        sub_limit = st.number_input("取得件数 ", min_value=10, max_value=500, value=100, step=10)

    status_param = "" if status_filter == "（すべて）" else status_filter
    user_id = get_user_id(username) if username else None

    try:
        submissions = fetch_submissions(user_id, status_param, int(sub_limit))
    except requests.exceptions.ConnectionError:
        st.error("バックエンドに接続できません。")
        submissions = []

    if submissions:
        df_sub = pd.DataFrame(submissions)
        df_sub["status"] = df_sub["status"].map(
            lambda s: f"{STATUS_ICONS.get(s, '⚪')} {s}"
        )
        df_sub["submitted_at"] = (
            pd.to_datetime(df_sub["submitted_at"])
            .dt.tz_localize("UTC")
            .dt.tz_convert("Asia/Tokyo")
            .dt.strftime("%Y-%m-%d %H:%M")
        )
        df_sub = df_sub.rename(columns={
            "id": "ID",
            "problem_id": "問題 ID",
            "status": "結果",
            "language": "言語",
            "execution_time_ms": "実行時間(ms)",
            "memory_kb": "メモリ(KB)",
            "submitted_at": "提出日時",
        })
        st.caption(f"{len(df_sub)} 件")
        st.dataframe(
            df_sub[["ID", "問題 ID", "結果", "言語", "実行時間(ms)", "メモリ(KB)", "提出日時"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        if not username:
            st.info("サイドバーにユーザー名を入力すると、そのユーザーの提出のみ表示されます。")
        else:
            st.info("提出データがありません。[Sync](/3_Sync) ページで同期してください。")
