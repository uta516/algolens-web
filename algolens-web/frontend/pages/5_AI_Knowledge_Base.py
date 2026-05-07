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


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_study_guide(uname: str):
    try:
        r = requests.get(f"{API_BASE}/knowledge/study_guide/{uname}", timeout=60)
    except requests.exceptions.ConnectionError:
        return None, "connection_error"
    if r.status_code == 404:
        return None, "user_not_found"
    if r.status_code in (401, 503):
        return None, f"invalid_key:{_extract_detail(r)}"
    if r.status_code == 429:
        return None, "quota_exceeded"
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
    col2.metric("生成日時", patterns["generated_at"][:16].replace("T", " ") + " JST")

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

st.divider()

# ============================================================
# セクション 3: 今後の学習方針 (Next Action Plan)
# ============================================================

st.header("③ 今後の学習方針 (Next Action Plan)", divider="orange")
st.markdown(
    f"**{username}** のC問題提出履歴（WA・TLE等）を AI 家庭教師が分析し、"
    "「次に何を勉強すべきか」を提案します。"
)

if not username:
    st.info("サイドバーにユーザー名を入力してください。")
    st.stop()

if st.button("🎯 学習方針を再生成（Gemini API 呼び出し）", key="btn_study_guide"):
    fetch_study_guide.clear()
    st.rerun()

with st.spinner("提出データを元に学習方針を生成中..."):
    guide, err_g = fetch_study_guide(username)

if err_g:
    _show_error(err_g)
elif guide:
    st.caption(f"生成日時: {guide['generated_at'][:16].replace('T', ' ')} JST")

    with st.container(border=True):
        st.subheader("🔍 現状の弱点分析")
        st.warning(guide["current_weakness"])

    with st.container(border=True):
        st.subheader("💻 習得すべき解法・コードパターン")
        st.markdown(guide["required_code_pattern"])

    with st.container(border=True):
        st.subheader("📚 推奨アクションプラン")
        st.info(guide["recommended_practice"])

st.divider()

# ============================================================
# セクション 4: 典型アルゴリズム スニペット集
# ============================================================

st.header("④ 典型アルゴリズム スニペット集", divider="violet")
st.markdown("AtCoder C問題でよく使う **7大パターン** のコードテンプレートです。")

with st.expander("🔎 ① 全探索（bit全探索 / itertools）"):
    st.markdown("**用途**: N が小さい（≦20程度）とき、すべての組み合わせを列挙して答えを求める。")
    st.code("""\
# ── bit全探索 ──
# N個の要素を「選ぶ/選ばない」の全パターン (2^N 通り)
n = 4
items = [1, 2, 3, 4]
for bit in range(1 << n):
    selected = [items[i] for i in range(n) if bit >> i & 1]
    print(selected)

# ── itertools.product ──
# 各桁が複数の値を取る全パターン（例: 3桁それぞれ 0〜2）
from itertools import product
for combo in product(range(3), repeat=3):
    print(combo)   # (0,0,0), (0,0,1), ...

# ── combinations / permutations ──
from itertools import combinations, permutations
for c in combinations([1, 2, 3, 4], 2):  # nCr
    print(c)
for p in permutations([1, 2, 3], 2):      # nPr
    print(p)
""", language="python")

with st.expander("📊 ② DP（1次元DP / 部分和問題）"):
    st.markdown("**用途**: 「〇〇を達成できるか」「最大・最小値は？」を部分問題に分解して解く。")
    st.code("""\
# ── 部分和問題（ちょうど S にできるか）──
# dp[j] = 合計 j が作れるかどうか
n, S = 4, 6
items = [1, 2, 3, 4]
dp = [False] * (S + 1)
dp[0] = True
for x in items:
    for j in range(S, x - 1, -1):  # 逆順で更新（01ナップサック）
        if dp[j - x]:
            dp[j] = True
print(dp[S])   # True なら達成可能

# ── 最大連続部分和（Kadane's algorithm）──
arr = [-2, 1, -3, 4, -1, 2, 1, -5, 4]
dp = [0] * len(arr)
dp[0] = arr[0]
for i in range(1, len(arr)):
    dp[i] = max(arr[i], dp[i - 1] + arr[i])
print(max(dp))   # 6
""", language="python")

with st.expander("🗺️ ③ 実装（dx/dy配列を使った2次元グリッドBFS）"):
    st.markdown("**用途**: マス目上の移動・BFS最短距離など、隣接4マスを処理する定番実装。")
    st.code("""\
from collections import deque

H, W = 5, 5
grid = [list(input()) for _ in range(H)]  # 'S', 'G', '#', '.' など
dx = [1, -1, 0,  0]
dy = [0,  0, 1, -1]

# スタート位置を探す
sx, sy = 0, 0
for i in range(H):
    for j in range(W):
        if grid[i][j] == 'S':
            sx, sy = i, j

# BFS で最短距離
dist = [[-1] * W for _ in range(H)]
dist[sx][sy] = 0
q = deque([(sx, sy)])
while q:
    x, y = q.popleft()
    for d in range(4):
        nx, ny = x + dx[d], y + dy[d]
        if 0 <= nx < H and 0 <= ny < W and grid[nx][ny] != '#' and dist[nx][ny] == -1:
            dist[nx][ny] = dist[x][y] + 1
            q.append((nx, ny))
""", language="python")

with st.expander("🗂️ ④ ハッシュテーブル（Counter / defaultdict で O(1) 検索）"):
    st.markdown("**用途**: 要素の出現回数を素早く集計する。辞書の存在確認は平均 O(1)。")
    st.code("""\
from collections import Counter, defaultdict

# ── Counter: 頻度カウント ──
s = "abracadabra"
cnt = Counter(s)
print(cnt)                  # Counter({'a': 5, 'b': 2, 'r': 2, ...})
print(cnt['a'])             # 5
print(cnt.most_common(2))   # [('a', 5), ('b', 2)]

# ── defaultdict: KeyError が出ないグラフ構築 ──
graph = defaultdict(list)
for u, v in [(1, 2), (1, 3), (2, 4)]:
    graph[u].append(v)
    graph[v].append(u)

# ── 辞書で O(1) 存在確認 ──
seen = {}
for x in [3, 1, 4, 1, 5, 9, 2, 6, 5]:
    if x in seen:
        print(f"{x} は重複")
    seen[x] = True
""", language="python")

with st.expander("💰 ⑤ 貪欲法（区間スケジューリング）"):
    st.markdown(
        "**用途**: 局所的に最善の選択を繰り返すことで全体最適が得られる問題。"
        "「区間スケジューリング」「コイン問題」が典型。"
    )
    st.code("""\
# ── 区間スケジューリング（終了時刻でソートして貪欲）──
# できるだけ多くの区間を重ならないよう選ぶ
intervals = [(1,4),(3,5),(0,6),(5,7),(3,9),(5,9),(6,10),(8,11)]
intervals.sort(key=lambda x: x[1])  # 終了時刻昇順

count = 0
last_end = -1
for s, e in intervals:
    if s >= last_end:       # 直前の区間と重ならない
        count += 1
        last_end = e
print(count)   # 4

# ── コインの両替 ──
coins = [500, 100, 50, 10, 5, 1]
amount = 1234
result = []
for c in coins:
    result.append(amount // c)
    amount %= c
print(result)   # [2, 2, 0, 3, 0, 4]
""", language="python")

with st.expander("🔢 ⑥ ソート（lambda を使った複数キーソート）"):
    st.markdown(
        "**用途**: タプルや複数条件での並び替え。"
        "Python の `sorted()` / `.sort()` は安定ソート（Timsort, O(N log N)）。"
    )
    st.code("""\
# ── 基本ソート ──
arr = [3, 1, 4, 1, 5, 9]
print(sorted(arr))               # 昇順
print(sorted(arr, reverse=True)) # 降順

# ── 複数キーソート ──
# 1st key: スコア降順、2nd key: 年齢昇順
students = [("Alice", 90, 20), ("Bob", 85, 22), ("Carol", 90, 19)]
students.sort(key=lambda x: (-x[1], x[2]))
print(students)
# [('Carol', 90, 19), ('Alice', 90, 20), ('Bob', 85, 22)]

# ── 絶対値でソート ──
arr2 = [-5, 3, -1, 4, -2]
print(sorted(arr2, key=abs))   # [-1, -2, 3, 4, -5]

# ── 文字列を長さでソート ──
words = ["banana", "apple", "cherry", "fig"]
print(sorted(words, key=len))  # ['fig', 'apple', 'banana', 'cherry']
""", language="python")

with st.expander("🔍 ⑦ 二分探索（bisect_left/right / めぐる式）"):
    st.markdown(
        "**用途**: ソート済み列での値の位置特定 O(log N)。"
        "「〇〇を満たす最小/最大値」を求めるめぐる式も頻出。"
    )
    st.code("""\
import bisect

# ── bisect_left / bisect_right ──
a = [1, 3, 3, 5, 7, 9]
x = 3
print(bisect.bisect_left(a, x))   # 1  (x 以上が始まる最左インデックス)
print(bisect.bisect_right(a, x))  # 3  (x より大きい最左インデックス)

# x の個数
count = bisect.bisect_right(a, x) - bisect.bisect_left(a, x)
print(count)   # 2

# x 以下の要素数
print(bisect.bisect_right(a, x))  # 3

# ── めぐる式二分探索 ──
# ok(m) が False→...→True→... の単調性を持つとき「True になる最小の m」を探す
def ok(m: int) -> bool:
    return m * m >= 10   # 例: m^2 >= 10 を満たす最小整数

lo, hi = 0, 10**9
while lo + 1 < hi:
    mid = (lo + hi) // 2
    if ok(mid):
        hi = mid
    else:
        lo = mid
print(hi)   # 4  (4^2=16>=10, 3^2=9<10)
""", language="python")
