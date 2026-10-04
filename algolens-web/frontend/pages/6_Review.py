import time

import requests
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="振り返り | AlgoLens", page_icon="🧑‍🏫", layout="wide")
st.title("🧑‍🏫 振り返り")
st.caption("コンテストの提出から、最小修正版・ずれの解説・もっと良い解き方・次に解く問題を出します")

username = st.sidebar.text_input(
    "AtCoder ユーザー名",
    value=st.session_state.get("username", ""),
    placeholder="例: hiyokosann",
    help="提出の取り込みと、AC 済みかどうかの判定に使います",
)
if username:
    st.session_state["username"] = username

VERDICT_ICON = {"AC": "✅", "WA": "❌", "TLE": "⏱️", "RE": "💥"}


# ============================================================
# ユーティリティ
# ============================================================

def _extract_detail(r) -> str:
    try:
        return r.json().get("detail", str(r.status_code))
    except Exception:
        return str(r.status_code)


def _get(path: str, **params):
    """GET して (json, エラーメッセージ) を返す。"""
    try:
        r = requests.get(f"{API_BASE}{path}", params=params, timeout=120)
    except requests.exceptions.ConnectionError:
        return None, "バックエンドに接続できません。FastAPI が起動しているか確認してください。"
    if r.status_code >= 400:
        return None, f"エラー ({r.status_code}): {_extract_detail(r)}"
    return r.json(), None


@st.cache_data(ttl=300, show_spinner=False)
def fetch_contests(uname: str):
    return _get("/review/contests", username=uname)


def _problem_links(problems: list[dict]) -> None:
    if not problems:
        st.write("なし")
        return
    for p in problems:
        diff = f"（diff {p['difficulty']:.0f}）" if p.get("difficulty") is not None else ""
        reasons = " / ".join(p["reasons"])
        st.markdown(f"- [{p['problem_id']} {p['title']}]({p['url']}) {diff} — {reasons}")


def _similar(payload: dict) -> None:
    left, right = st.columns(2)
    with left:
        st.markdown("**📘 参考（AC 済み）**")
        _problem_links(payload.get("reference", []))
    with right:
        st.markdown("**🎯 次に解く問題**")
        _problem_links(payload.get("next_problems", []))


def _sample_cases(cases: list[dict]) -> None:
    if not cases:
        st.write("サンプルでの確認は行っていません。")
    # 問題ごとの expander の中でも使うため、expander は入れ子にせず、通らなかったケースだけ中身を出す
    for case in cases:
        icon = "✅" if case["status"] == "AC" else "❌"
        st.markdown(f"{icon} サンプル {case['index']}: **{case['status']}**")
        if case["status"] == "AC":
            continue
        cols = st.columns(3)
        cols[0].caption("入力"); cols[0].code(case["input"])
        cols[1].caption("期待する出力"); cols[1].code(case["expected"])
        cols[2].caption("実際の出力"); cols[2].code(case["actual"] or "（なし）")
        if case["stderr"]:
            st.caption("エラー"); st.code(case["stderr"])


def verification_summary(result: dict) -> str:
    """修正版について何を確かめたかを 1 行で（例: サンプル 3/3 通過・最大サイズの入力 0.8 秒・提出での確認はまだ）。"""
    cases = result["sample_cases"]
    passed = sum(1 for c in cases if c["status"] == "AC")
    parts = [f"サンプル {passed}/{len(cases)} 通過" if cases else "サンプル 確認なし"]

    stress = result.get("stress")
    if stress is None:
        parts.append("最大サイズの入力 未実行")
    elif stress["status"] == "ok":
        parts.append(
            f"最大サイズの入力 {stress['seconds']:.1f} 秒"
            f"（{stress['interpreter']}・制限 {stress['time_limit']:g} 秒）"
        )
    elif stress["status"] == "TLE":
        parts.append(f"最大サイズの入力 {stress['time_limit']:g} 秒で時間切れ（{stress['interpreter']}）")
    else:
        parts.append("最大サイズの入力 確認できず")

    status = result.get("fix_status")
    if status is None:
        parts.append("提出での確認はまだ")
    elif status == "確認済み":
        parts.append("提出で AC（確認済み）")
    else:
        parts.append(f"提出で {result.get('submitted_verdict')}（修正失敗）")
    return "・".join(parts)


def render_submit_result_form(result: dict) -> None:
    """修正版を提出した結果を戻す欄。AC 以外なら、その結果を伝えて修正版を作り直す。"""
    log_id = result.get("log_id")
    if log_id is None or result.get("fix_status") == "確認済み":
        return
    if result.get("fix_status") == "修正失敗":
        st.caption(f"この修正版は提出で {result.get('submitted_verdict')} でした。")
    with st.form(f"submit_result_{log_id}"):
        col1, col2 = st.columns([1, 2])
        verdict = col1.selectbox("修正版を提出した結果", ["AC", "WA", "TLE", "RE"], key=f"submit_verdict_{log_id}")
        col2.write("")
        sent = col2.form_submit_button("結果を記録する（AC 以外なら作り直す）")
    if not sent:
        return
    with st.spinner("記録しています（AC 以外なら、結果を伝えて修正版を作り直します。1 分ほどかかることがあります）..."):
        try:
            r = requests.post(
                f"{API_BASE}/tutor/logs/{log_id}/submit-result",
                json={"verdict": verdict, "username": username or None},
                timeout=900,
            )
        except requests.exceptions.RequestException as e:
            st.error(f"通信エラー（{e}）")
            return
    if r.status_code >= 400:
        st.error(f"エラー ({r.status_code}): {_extract_detail(r)}")
        return
    body = r.json()
    # 手入力の結果を表示中なら差し替える（振り返りの一覧は再読み込みで反映される）
    current = st.session_state.get("tutor_result")
    if current and current.get("log_id") == log_id:
        st.session_state["tutor_result"] = body["result"] or current | {
            "fix_status": body["fix_status"], "submitted_verdict": body["submitted_verdict"],
        }
    st.rerun()


def render_mistake(result: dict) -> None:
    """WA / TLE / RE の家庭教師の結果。"""
    for w in result["warnings"]:
        st.warning(w)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ミスの種類", result["mistake_type"])
    c2.metric("書き方 / 考え方", result["mistake_level"])
    c3.metric("同じミスの過去回数", f"{result['past_same_type_count']} 回")
    ops = result.get("estimated_ops")
    c4.metric(
        "修正版の計算量", result.get("complexity") or "不明",
        help=f"制約の上限での計算回数の目安: {ops:.1e} 回" if ops is not None else "計算回数の目安: 不明",
    )

    st.markdown(f"**確かめたこと:** {verification_summary(result)}")
    st.caption(f"修正案の作成回数: {result['attempts']} 回")
    render_submit_result_form(result)

    st.markdown(f"**ずれ:** {result['gap_summary']}")
    st.markdown(f"**正しい考え方:** {result['correct_idea']}")
    st.markdown(f"**教訓:** {result['lesson']}")

    tab_fix, tab_diff, tab_orig, tab_samples = st.tabs(["修正版コード", "差分", "元のコード", "サンプル結果"])
    with tab_fix:
        st.code(result["fixed_code"], language="python")
    with tab_diff:
        st.caption(f"変更 {result['diff_lines']} 行 / 元コード {result['total_lines']} 行")
        st.code(result["diff"] or "（差分なし）", language="diff")
    with tab_orig:
        st.code(result["original_code"], language="python")
    with tab_samples:
        _sample_cases(result["sample_cases"])

    st.markdown("**解説**")
    st.markdown(result["explanation"] or "（解説を生成できませんでした）")
    _similar(result)


def render_ac(payload: dict, original_code: str | None) -> None:
    """AC の提出への提案（計算量が良くなる / 行数が半分以下の場合だけ）。"""
    for w in payload["warnings"]:
        st.warning(w)
    suggestion = payload.get("suggestion")
    if suggestion:
        st.success(f"💡 {payload['summary']}（{suggestion['improvement']}）")
    else:
        st.info(f"👍 {payload['summary']}")
    if payload.get("note"):
        st.caption(payload["note"])
    if payload.get("current_complexity"):
        st.markdown(f"**今の計算量:** {payload['current_complexity']}")
    if payload.get("correct_idea"):
        st.markdown(f"**考え方:** {payload['correct_idea']}")
    if payload.get("explanation"):
        st.markdown(payload["explanation"])
    if suggestion and suggestion.get("reason"):
        st.markdown("**提案のポイント**")
        st.markdown(suggestion["reason"])

    if suggestion:
        tab_new, tab_diff, tab_orig, tab_samples = st.tabs(["提案コード", "差分", "元のコード", "サンプル結果"])
        with tab_new:
            st.code(suggestion["code"], language="python")
        with tab_diff:
            st.caption(f"変更 {suggestion['diff_lines']} 行 / 元コード {suggestion['total_lines']} 行")
            st.code(suggestion["diff"] or "（差分なし）", language="diff")
        with tab_orig:
            st.code(original_code or "", language="python")
        with tab_samples:
            _sample_cases(payload.get("sample_cases", []))
    elif original_code:
        (tab_orig,) = st.tabs(["元のコード"])
        with tab_orig:
            st.code(original_code, language="python")
    _similar(payload)


def process_report(report_id: int, label: str) -> dict | None:
    """1 問処理する。成功すれば結果、失敗すればエラーを表示して None。"""
    try:
        res = requests.post(f"{API_BASE}/review/process/{report_id}", timeout=900)
    except requests.exceptions.RequestException as e:
        st.error(f"{label}: 通信エラー（{e}）")
        return None
    if res.status_code >= 400:
        st.error(f"{label}: {_extract_detail(res)}")
        return None
    return res.json()


def render_code_form(r: dict) -> None:
    """提出コードが手元のフォルダにない問題に、コードを貼り付けて処理する欄を出す。"""
    st.warning(
        "提出コードが手元のフォルダにありません。上の「提出」リンクを開いてコードをコピーし、"
        "ここに貼り付けてください（または submissions/<コンテスト>/<記号>.py に保存してから取り込み直す）。"
    )
    with st.form(f"code_form_{r['id']}"):
        code = st.text_area("提出コード（Python）", height=250, key=f"code_{r['id']}")
        submitted = st.form_submit_button("このコードで処理する", type="primary")
    if not submitted:
        return
    if not code.strip():
        st.warning("コードを貼り付けてください。")
        return
    res = requests.put(f"{API_BASE}/review/reports/{r['id']}/code", json={"code": code}, timeout=30)
    if res.status_code >= 400:
        st.error(f"保存できませんでした: {_extract_detail(res)}")
        return
    with st.spinner(f"{r['title']} を処理しています（1 分ほどかかることがあります）..."):
        out = process_report(r["id"], r["title"])
    if out:
        st.rerun()


def render_report(r: dict) -> None:
    url = f"https://atcoder.jp/contests/{r['contest_id']}/tasks/{r['problem_id']}"
    sub_url = f"https://atcoder.jp/contests/{r['contest_id']}/submissions/{r['submission_id']}"
    st.markdown(f"[問題ページ]({url}) ・ [提出 #{r['submission_id']}]({sub_url}) ・ {r['language']}")
    if r["status"] != "done":
        if r["kind"] in ("ac", "mistake") and not r["original_code"]:
            render_code_form(r)
        else:
            if r["error"]:
                st.warning(f"前回のエラー: {r['error']}")
            st.info("未処理です。「最新コンテストを取り込む」を押すと続きから処理します。")
        return
    payload = r["payload"] or {}
    if r["kind"] == "skipped":
        st.info(f"対象外: {payload.get('reason', '')}")
    elif r["kind"] == "ac":
        render_ac(payload, r["original_code"])
    else:
        render_mistake(payload)


def run_import(contest_id: str) -> None:
    """取り込み → pending の問題を 1 問ずつ処理し、進み具合を表示する。"""
    try:
        r = requests.post(
            f"{API_BASE}/review/import", json={"username": username, "contest_id": contest_id}, timeout=120
        )
    except requests.exceptions.ConnectionError:
        st.error("バックエンドに接続できません。FastAPI が起動しているか確認してください。")
        return
    if r.status_code >= 400:
        st.error(f"取り込みに失敗しました ({r.status_code}): {_extract_detail(r)}")
        return
    body = r.json()
    reports = body["reports"]
    for w in body.get("warnings", []):
        st.warning(w)
    if not body.get("warnings"):
        st.caption(f"提出データを同期しました（新しく追加した提出: {body['synced_submissions']} 件）")
    pending = [x for x in reports if x["status"] != "done"]
    if not pending:
        st.success(f"{contest_id} の {len(reports)} 問はすべて処理済みです。")
        return

    st.write(f"{contest_id}: {len(reports)} 問中 {len(pending)} 問を処理します（処理済みの問題は作り直しません）")
    bar = st.progress(0.0)
    log = st.container()
    started = time.time()
    done = calls = 0
    need_code = []
    for i, rep in enumerate(pending):
        label = f"{rep['title']}（{rep['verdict']}）"
        bar.progress(i / len(pending), text=f"{i + 1}/{len(pending)}: {label} を処理中...")
        t0 = time.time()
        try:
            res = requests.post(f"{API_BASE}/review/process/{rep['id']}", timeout=900)
        except requests.exceptions.RequestException as e:
            log.error(f"{label}: 通信エラー（{e}）。もう一度取り込むと続きから再開します。")
            break
        if res.status_code == 422:
            need_code.append(rep["title"])
            log.write(f"📋 {label}: 提出コードが手元にないため、あとで貼り付けてください")
            continue
        if res.status_code >= 400:
            log.error(f"{label}: {_extract_detail(res)}")
            if res.status_code in (409, 429, 503):
                log.warning("処理を中断しました。少し時間をおいてもう一度取り込むと、続きから再開します。")
                break
            continue
        out = res.json()
        done += 1
        calls += out["gemini_calls"]
        log.write(f"✔ {label}: {time.time() - t0:.0f} 秒 / Gemini {out['gemini_calls']} 回")
    bar.progress(1.0, text="完了")
    st.success(f"{done}/{len(pending)} 問を処理しました（{time.time() - started:.0f} 秒、Gemini 呼び出し {calls} 回）")
    if need_code:
        st.info(f"提出コードの貼り付けが必要な問題: {', '.join(need_code)}（下の一覧から貼り付けられます）")


# ============================================================
# ページ本体
# ============================================================

tab_review, tab_manual = st.tabs(["📅 コンテストの振り返り", "✍️ 手入力で解説"])

with tab_review:
    if not username:
        st.info("サイドバーに AtCoder ユーザー名を入力してください。")
    else:
        contests, err = fetch_contests(username)
        if err:
            fetch_contests.clear()  # エラーはキャッシュせず、次の表示で取り直す
            st.error(err)
        elif not contests:
            st.info("直近 10 回の ABC に提出が見つかりませんでした。")
        else:
            col1, col2 = st.columns([3, 1])
            options = {c["contest_id"]: c for c in contests}
            contest_id = col1.selectbox(
                "コンテスト",
                list(options),
                format_func=lambda cid: f"{options[cid]['title']}（提出 {options[cid]['submission_count']} 件）",
            )
            col2.write("")
            if col2.button("最新コンテストを取り込む", type="primary", use_container_width=True):
                run_import(contest_id)
                st.session_state["review_contest"] = contest_id

        st.divider()
        st.subheader("保存済みの振り返り")
        saved, err = _get("/review/saved-contests", username=username)
        if err:
            st.error(err)
        elif not saved:
            st.write("まだありません。上のボタンでコンテストを取り込んでください。")
        else:
            saved_ids = [s["contest_id"] for s in saved]
            default = st.session_state.get("review_contest")
            index = saved_ids.index(default) if default in saved_ids else 0
            labels = {s["contest_id"]: f"{s['contest_id']}（{s['done_count']}/{s['problem_count']} 問処理済み）" for s in saved}
            shown = st.selectbox("表示するコンテスト", saved_ids, index=index, format_func=labels.get)
            reports, err = _get("/review/reports", username=username, contest_id=shown)
            if err:
                st.error(err)
            for r in reports or []:
                icon = VERDICT_ICON.get(r["verdict"], "➖")
                wa = f" ・ WA 等 {r['wa_count']} 回" if r["wa_count"] else ""
                pending = "" if r["status"] == "done" else " ・ 未処理"
                with st.expander(f"{icon} {r['title']} — {r['verdict']}{wa}{pending}"):
                    render_report(r)

with tab_manual:
    with st.form("tutor_form"):
        col1, col2 = st.columns([3, 1])
        problem_id = col1.text_input("問題ID", placeholder="例: abc300_c")
        verdict = col2.selectbox("判定", ["WA", "TLE", "RE"])
        code = st.text_area("提出コード（Python）", height=300)
        submitted = st.form_submit_button("解説してもらう", type="primary")

    if submitted:
        if not problem_id.strip() or not code.strip():
            st.warning("問題IDとコードを入力してください。")
        else:
            payload = {
                "problem_id": problem_id.strip(),
                "code": code,
                "verdict": verdict,
                "username": username or None,
            }
            with st.spinner("Gemini が修正案を作り、サンプルと最大サイズの入力で確認しています（1 分ほどかかることがあります）..."):
                try:
                    r = requests.post(f"{API_BASE}/tutor/explain", json=payload, timeout=300)
                except requests.exceptions.ConnectionError:
                    r = None
                    st.error("バックエンドに接続できません。FastAPI が起動しているか確認してください。")
                except requests.exceptions.Timeout:
                    r = None
                    st.error("タイムアウトしました。しばらくしてからもう一度試してください。")
            if r is not None:
                if r.status_code >= 400:
                    st.error(f"エラー ({r.status_code}): {_extract_detail(r)}")
                else:
                    st.session_state["tutor_result"] = r.json()

    result = st.session_state.get("tutor_result")
    if result:
        st.divider()
        render_mistake(result)
