import requests
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="AI Knowledge Base | AlgoLens", page_icon="🧠", layout="wide")
st.title("🧠 AI Knowledge Base")
st.caption("Gemini が hiyokosann の提出データを解析し、パターンと学びを自動生成します")

# サイドバー: ユーザー名
username = st.sidebar.text_input(
    "AtCoder ユーザー名",
    value=st.session_state.get("username", "hiyokosann"),
    placeholder="例: hiyokosann",
)
if username:
    st.session_state["username"] = username


# ============================================================
# ユーティリティ
# ============================================================

_APIKEY_URL = "https://aistudio.google.com/app/apikey"


def _server_error_msg(detail: str) -> str:
    return (
        "バックエンドでエラーが発生しました。"
        "APIキーの設定やバックエンドのログを確認してください。\n\n"
        f"詳細: `{detail}`"
    )


def _extract_detail(r) -> str:
    try:
        return r.json().get("detail", str(r.status_code))
    except Exception:
        return str(r.status_code)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_patterns():
    try:
        r = requests.get(f"{API_BASE}/knowledge/patterns", timeout=60)
    except requests.exceptions.ConnectionError:
        return None, "connection_error"
    if r.status_code == 404:
        return None, "sync_needed"
    if r.status_code in (401, 503):
        return None, f"invalid_key:{_extract_detail(r)}"
    if r.status_code == 429:
        return None, "quota_exceeded"
    if r.status_code >= 400:
        return None, f"server_error:{_extract_detail(r)}"
    return r.json(), None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_weekly(uname: str):
    try:
        r = requests.get(f"{API_BASE}/knowledge/weekly-insights/{uname}", timeout=60)
    except requests.exceptions.ConnectionError:
        return None, "connection_error"
    if r.status_code == 404:
        return None, "user_not_found"
    if r.status_code in (401, 503):
        return None, f"invalid_key:{_extract_detail(r)}"
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", str(r.status_code))
        except Exception:
            detail = str(r.status_code)
        return None, f"server_error:{detail}"
    return r.json(), None


def _show_error(err: str):
    if err == "connection_error":
        st.error("バックエンドに接続できません。サーバーが起動しているか確認してください。")
    elif err == "sync_needed":
        st.warning("C 問題のデータが DB にありません。**Sync** ページで問題データを同期してください。")
    elif err == "user_not_found":
        st.warning(f"ユーザー `{username}` が見つかりません。Sync ページで登録してください。")
    elif err and err.startswith("invalid_key:"):
        detail = err.removeprefix("invalid_key:")
        st.error(
            "**Gemini API キーが無効です（400 API key not valid）。**\n\n"
            f"詳細: `{detail}`\n\n"
            "**対処法:**\n"
            "1. [Google AI Studio](" + _APIKEY_URL + ") で新しい API キーを発行する\n"
            "2. `backend/.env` の `GEMINI_API_KEY=` を新しいキーに更新する\n"
            "3. バックエンドを再起動して `http://localhost:8000/knowledge/ping` で疎通確認する"
        )
    elif err == "quota_exceeded":
        st.warning(
            "**Gemini API の無料枠クォータを超過しています（429）。**\n\n"
            "- しばらく待ってから再度お試しください（通常 1 分程度でリセット）\n"
            "- 使用量の確認: https://ai.dev/rate-limit"
        )
    elif err and err.startswith("server_error:"):
        detail = err.removeprefix("server_error:")
        st.error(_server_error_msg(detail))
    else:
        st.error("予期しないエラーが発生しました。バックエンドのログを確認してください。")


def _algo_chips(algorithms: list[str]):
    colors = ["#0066CC", "#007744", "#AA4400", "#660088", "#CC6600", "#005588", "#008877", "#883300"]
    cols = st.columns(min(len(algorithms), 4))
    for i, algo in enumerate(algorithms):
        color = colors[i % len(colors)]
        cols[i % 4].markdown(
            f'<span style="background:{color};color:white;padding:4px 10px;border-radius:12px;'
            f'font-size:0.85rem;font-weight:600;">{algo}</span>',
            unsafe_allow_html=True,
        )


# ============================================================
# セクション 1: AI による C 問題パターン分析
# ============================================================

st.header("① AI による C 問題パターン分析", divider="blue")
st.markdown("難易度 **0〜799（灰・茶色）** の C 問題を Gemini が一括分析します。")

if st.button("🔍 パターン分析を再生成（Gemini API 呼び出し）", key="btn_patterns"):
    fetch_patterns.clear()
    st.rerun()

with st.spinner("Gemini が分析中です... 初回は 15〜30 秒かかる場合があります"):
    patterns, err = fetch_patterns()

if err:
    _show_error(err)
elif patterns:
    col1, col2 = st.columns(2)
    col1.metric("分析対象 C 問題数", f"{patterns['total_problems']} 問")
    col2.metric("生成日時", patterns["generated_at"][:16].replace("T", " ") + " UTC")

    with st.container(border=True):
        st.subheader("📐 制約の傾向")
        st.info(patterns["constraints_tendency"])

    with st.container(border=True):
        st.subheader("⚙️ 頻出アルゴリズム")
        algos = patterns.get("frequent_algorithms", [])
        if algos:
            _algo_chips(algos)
            st.write("")
        else:
            st.write("データなし")

    with st.container(border=True):
        st.subheader("💡 解法の定石")
        st.success(patterns["solving_patterns"])

    with st.expander("📋 分析に使用したサンプル問題（上位10件）"):
        for p in patterns.get("sample_problems", []):
            diff_str = f"{p['difficulty']:.0f}" if p["difficulty"] else "不明"
            link = f"[{p['title']}]({p['url']})" if p.get("url") else p["title"]
            st.markdown(f"- {link} — difficulty: **{diff_str}**")

st.divider()

# ============================================================
# セクション 2: Weekly Insights
# ============================================================

st.header("② Weekly Insights", divider="green")
st.markdown(f"**{username}** の直近の提出から「使い回せるコード」と「学んだ点」を AI が要約します。")

if not username:
    st.info("サイドバーにユーザー名を入力してください。")
    st.stop()

if st.button("📅 Weekly Insights を再生成（Gemini API 呼び出し）", key="btn_weekly"):
    fetch_weekly.clear()
    st.rerun()

with st.spinner("提出データを分析中..."):
    weekly, err_w = fetch_weekly(username)

if err_w:
    _show_error(err_w)
elif weekly:
    col1, col2, col3 = st.columns(3)
    col1.metric("対象期間", f"{weekly['week_start']} 〜 {weekly['week_end']}")
    col2.metric("総提出数", weekly["total_submissions"])
    col3.metric("AC 数", weekly["ac_count"])

    if weekly["total_submissions"] == 0:
        st.info("提出データがありません。")
    else:
        col_left, col_right = st.columns(2)
        with col_left:
            with st.container(border=True):
                st.subheader("♻️ 使い回せるコードパターン")
                st.markdown(weekly["reusable_snippets"])
        with col_right:
            with st.container(border=True):
                st.subheader("📖 今週の学び")
                st.markdown(weekly["key_learnings"])
