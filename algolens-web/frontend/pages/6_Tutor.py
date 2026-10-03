import requests
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="家庭教師 | AlgoLens", page_icon="🧑‍🏫", layout="wide")
st.title("🧑‍🏫 家庭教師")
st.caption("WA / TLE / RE になったコードから、最小修正版・ずれの解説・次に解く問題を出します")

username = st.sidebar.text_input(
    "AtCoder ユーザー名",
    value=st.session_state.get("username", ""),
    placeholder="例: hiyokosann",
    help="AC 済みかどうかの判定に使います（空欄なら DB の全提出を見ます）",
)
if username:
    st.session_state["username"] = username


def _extract_detail(r) -> str:
    try:
        return r.json().get("detail", str(r.status_code))
    except Exception:
        return str(r.status_code)


def _problem_links(problems: list[dict]) -> None:
    if not problems:
        st.write("なし")
        return
    for p in problems:
        diff = f"（diff {p['difficulty']:.0f}）" if p.get("difficulty") is not None else ""
        reasons = " / ".join(p["reasons"])
        st.markdown(f"- [{p['problem_id']} {p['title']}]({p['url']}) {diff} — {reasons}")


# ============================================================
# 入力
# ============================================================

with st.form("tutor_form"):
    col1, col2 = st.columns([3, 1])
    problem_id = col1.text_input("問題ID", placeholder="例: abc300_c")
    verdict = col2.selectbox("判定", ["WA", "TLE", "RE"])
    code = st.text_area("提出コード（Python）", height=300)
    submitted = st.form_submit_button("解説してもらう", type="primary")

if submitted:
    if not problem_id.strip() or not code.strip():
        st.warning("問題IDとコードを入力してください。")
        st.stop()
    payload = {
        "problem_id": problem_id.strip(),
        "code": code,
        "verdict": verdict,
        "username": username or None,
    }
    with st.spinner("Gemini が修正案を作り、サンプルで確認しています（1 分ほどかかることがあります）..."):
        try:
            r = requests.post(f"{API_BASE}/tutor/explain", json=payload, timeout=300)
        except requests.exceptions.ConnectionError:
            st.error("バックエンドに接続できません。FastAPI が起動しているか確認してください。")
            st.stop()
        except requests.exceptions.Timeout:
            st.error("タイムアウトしました。しばらくしてからもう一度試してください。")
            st.stop()
    if r.status_code >= 400:
        st.error(f"エラー ({r.status_code}): {_extract_detail(r)}")
        st.stop()
    st.session_state["tutor_result"] = r.json()

result = st.session_state.get("tutor_result")
if not result:
    st.stop()

# ============================================================
# 結果
# ============================================================

st.divider()
for w in result["warnings"]:
    st.warning(w)

c1, c2, c3, c4 = st.columns(4)
c1.metric("ミスの種類", result["mistake_type"])
c2.metric("書き方 / 考え方", result["mistake_level"])
c3.metric("同じミスの過去回数", f"{result['past_same_type_count']} 回")
samples = {True: "通過", False: "不通過", None: "確認なし"}[result["samples_passed"]]
c4.metric("サンプル", samples, help=f"修正案の作成回数: {result['attempts']} 回")

st.markdown(f"**ずれ:** {result['gap_summary']}")
st.markdown(f"**正しい考え方:** {result['correct_idea']}")
st.markdown(f"**教訓:** {result['lesson']}")

tab_fix, tab_diff, tab_samples = st.tabs(["修正版コード", "差分", "サンプル結果"])
with tab_fix:
    st.code(result["fixed_code"], language="python")
with tab_diff:
    st.caption(f"変更 {result['diff_lines']} 行 / 元コード {result['total_lines']} 行")
    st.code(result["diff"] or "（差分なし）", language="diff")
with tab_samples:
    if not result["sample_cases"]:
        st.write("サンプルでの確認は行っていません。")
    for case in result["sample_cases"]:
        icon = "✅" if case["status"] == "AC" else "❌"
        with st.expander(f"{icon} サンプル {case['index']}: {case['status']}"):
            st.text("入力"); st.code(case["input"])
            st.text("期待する出力"); st.code(case["expected"])
            st.text("実際の出力"); st.code(case["actual"] or "（なし）")
            if case["stderr"]:
                st.text("エラー"); st.code(case["stderr"])

st.subheader("解説")
st.markdown(result["explanation"] or "（解説を生成できませんでした）")

left, right = st.columns(2)
with left:
    st.subheader("📘 参考（AC 済み）")
    _problem_links(result["reference"])
with right:
    st.subheader("🎯 次に解く問題")
    _problem_links(result["next_problems"])
