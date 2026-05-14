import pandas as pd
import requests
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Knowledge Base | AlgoLens", page_icon="📚", layout="wide")
st.title("📚 Knowledge Base")
st.caption("競技プログラミングで使える定石・スニペット集")

# ============================================================
# API ユーティリティ
# ============================================================

def _fetch(category: str | None = None) -> list[dict]:
    try:
        params = {"category": category} if category else {}
        r = requests.get(f"{API_BASE}/knowledge/snippets", params=params, timeout=5)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def _post(title: str, tags: str, code: str, memo: str, category: str) -> tuple[bool, str]:
    try:
        r = requests.post(
            f"{API_BASE}/knowledge/snippets",
            json={"title": title, "tags": tags, "code": code, "memo": memo, "category": category},
            timeout=10,
        )
        return (True, "") if r.status_code == 201 else (False, r.text)
    except requests.exceptions.ConnectionError:
        return False, "バックエンドに接続できません。"


def _put(sid: str, title: str, tags: str, code: str, memo: str, category: str) -> tuple[bool, str]:
    try:
        r = requests.put(
            f"{API_BASE}/knowledge/snippets/{sid}",
            json={"title": title, "tags": tags, "code": code, "memo": memo, "category": category},
            timeout=10,
        )
        return (True, "") if r.status_code == 200 else (False, r.text)
    except requests.exceptions.ConnectionError:
        return False, "バックエンドに接続できません。"


def _delete(sid: str) -> tuple[bool, str]:
    try:
        r = requests.delete(f"{API_BASE}/knowledge/snippets/{sid}", timeout=10)
        return (True, "") if r.status_code == 204 else (False, r.text)
    except requests.exceptions.ConnectionError:
        return False, "バックエンドに接続できません。"


def render_snippet_card(snip: dict) -> None:
    """1件のスニペットを閲覧・編集・削除UIつきで表示する。"""
    sid = snip["id"]
    editing_key = f"editing_{sid}"
    is_editing = st.session_state.get(editing_key, False)
    date_str = snip.get("created_at", "")[:10]
    tags_str = snip.get("tags", "")

    label = f"📌 {snip['title']}"
    if tags_str:
        label += f"  `{tags_str}`"
    if date_str:
        label += f"  —  {date_str}"

    with st.expander(label, expanded=is_editing):
        if not is_editing:
            # ── 閲覧モード ──
            if snip.get("code", "").strip():
                st.code(snip["code"], language="python")
            if snip.get("memo", "").strip():
                st.info(snip["memo"])

            c1, c2, _ = st.columns([1, 1, 6])
            if c1.button("✏️ 編集", key=f"edit_btn_{sid}", use_container_width=True):
                st.session_state[editing_key] = True
                st.rerun()
            if c2.button("🗑️ 削除", key=f"del_btn_{sid}", use_container_width=True):
                ok, err = _delete(sid)
                if ok:
                    st.rerun()
                else:
                    st.error(f"削除に失敗しました: {err}")
        else:
            # ── 編集モード ──
            with st.form(key=f"edit_form_{sid}"):
                new_title = st.text_input("タイトル", value=snip["title"])
                new_tags  = st.text_input("タグ / キーワード", value=snip.get("tags", ""))
                new_code  = st.text_area("コード (Python)", value=snip.get("code", ""), height=180)
                new_memo  = st.text_area("メモ", value=snip.get("memo", ""), height=70)
                cs, cc = st.columns(2)
                save_btn   = cs.form_submit_button("💾 保存", use_container_width=True)
                cancel_btn = cc.form_submit_button("❌ キャンセル", use_container_width=True)

            if save_btn:
                ok, err = _put(
                    sid, new_title, new_tags, new_code, new_memo,
                    snip.get("category", "my_snippet"),
                )
                if ok:
                    st.session_state[editing_key] = False
                    st.rerun()
                else:
                    st.error(f"保存に失敗しました: {err}")
            if cancel_btn:
                st.session_state[editing_key] = False
                st.rerun()


def render_add_form(form_key: str, category: str, expander_label: str = "➕ 新しい項目を追加") -> None:
    """スニペット追加フォームを expander 内に表示する。"""
    with st.expander(expander_label, expanded=False):
        with st.form(form_key, clear_on_submit=True):
            title = st.text_input("タイトル", placeholder="例: 累積和テンプレート")
            tags  = st.text_input("タグ / キーワード", placeholder="例: 累積和, 配列")
            code  = st.text_area("コード (Python)", height=180, placeholder="# ここにコードを貼り付け")
            memo  = st.text_area("メモ", height=70, placeholder="使いどころや注意点など")
            submitted = st.form_submit_button("保存する")

        if submitted:
            if not title.strip():
                st.error("タイトルを入力してください。")
            else:
                ok, err = _post(title, tags, code, memo, category)
                if ok:
                    st.rerun()
                else:
                    st.error(f"保存に失敗しました: {err}")


# ============================================================
# タブ構成
# ============================================================
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["解法チートシート", "入力チートシート", "典型アルゴリズム", "マイ・スニペット", "リンク集"]
)

# ============================================================
# Tab 1: 解法チートシート
# ============================================================
with tab1:
    st.subheader("制約 N に対する計算量の目安")
    st.info("本番中に「TLEしそう？」と思ったらこの表を参照してください。")

    data = [
        ("N ≤ 12",     "O(2^N × N)",  "bit 全探索 + ループ"),
        ("N ≤ 20",     "O(2^N)",       "bit DP・集合 DP"),
        ("N ≤ 100",    "O(N³)",        "Floyd-Warshall・行列 DP"),
        ("N ≤ 1,000",  "O(N²)",        "二重ループ DP・バブルソート"),
        ("N ≤ 3×10⁵",  "O(N log N)",  "ソート・二分探索・BIT・セグ木"),
        ("N ≤ 10⁶",    "O(N)",         "累積和・グリーディ・尺取り法"),
        ("N ≤ 10⁹",    "O(log N)",     "二分探索（値域）・繰り返し二乗法"),
        ("N ≤ 10¹⁸",   "O(√N)",        "素因数分解・約数列挙"),
    ]
    df = pd.DataFrame(data, columns=["N の大きさ", "目安の計算量", "代表的なアルゴリズム"])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("制約から逆算する解法選択")
    st.markdown(
        "| 制約の目安 | 疑うべき解法 |\n"
        "|---|---|\n"
        "| N ≦ 20 | 2^N 全部試す（**bit全探索**） |\n"
        "| N ≦ 2,000 | N² 二重ループ / **DP** |\n"
        "| N ≦ 2×10⁵ | NlogN **ソート + 1重ループ・貪欲・二分探索** |\n"
        "| N ≧ 10⁹ | ループ不可 → **数式・規則性** |"
    )

    st.subheader("キーワードから疑うアルゴリズム")
    st.markdown(
        "| 問題文のキーワード | 真っ先に疑うアルゴリズム |\n"
        "|---|---|\n"
        "| 「順番を変えてもいい」 | **ソート** |\n"
        "| 「最大/最小」「最大化・最小化」 | **貪欲 / DP** |\n"
        "| 「条件を満たす組み合わせ」「場合の数」 | **数学 / DP** |\n"
        "| 「K番目」「K以上の最小」 | **二分探索** |\n"
        "| 「部分集合」「選ぶ/選ばない」 | **bit全探索 / DP** |\n"
        "| 「最短経路」「最短距離」 | **BFS / Dijkstra** |\n"
        "| 「区間の和」「累積」 | **累積和** |"
    )

    st.subheader("よくある TLE パターン")
    st.warning(
        "- `list.index()` や `in list` を繰り返す → `set` や `dict` に変える  \n"
        "- `str` を `+=` で連結するループ → `''.join(lst)` にする  \n"
        "- 再帰が深い → `sys.setrecursionlimit` を増やすか BFS/反復に変える"
    )

# ============================================================
# Tab 2: 入力チートシート
# ============================================================
with tab2:
    # ── 固定（ハードコード）セクション ─────────────────────
    st.subheader("Python 標準入力パターン（固定）")
    st.info("AtCoder の入力形式別スニペット。コピペして即使用できます。")

    _hardcoded_inputs = [
        ("整数 1 つ",                   "N = int(input())"),
        ("スペース区切り整数（2 変数）", "N, M = map(int, input().split())"),
        ("スペース区切り整数リスト",     "A = list(map(int, input().split()))"),
        ("N 行の整数（1 列）",           "A = [int(input()) for _ in range(N)]"),
        ("N 行・スペース区切り（2D）",   "data = [list(map(int, input().split())) for _ in range(N)]"),
        ("N個の文字列",                   "S = [input() for _ in range(N)]"),
        ("グリッド（文字）",             "grid = [input() for _ in range(H)]"),
        ("グリッド（整数）",             "grid = [list(map(int, input().split())) for _ in range(H)]"),
        ("1 行を文字のリストに",         "chars = list(input())"),
        ("無向グラフ（隣接リスト）",
         "node = [[] for _ in range(N)]\nu, v = map(int, input().split())\nnode[u].append(v)\nnode[v].append(u)"),
        ("配列A,Bをペアに変換",          "p = [[x, y] for x, y in zip(A, B)]"),
        ("切り上げ除算",                 "(A + B - 1) // B"),
        ("リストの中身をカウント",       "from collections import Counter\ncounts = Counter(A)"),
    ]
    for lbl, code in _hardcoded_inputs:
        st.markdown(f"**{lbl}**")
        st.code(code, language="python")

    st.subheader("高速入出力（大量 I/O 時）")
    st.code(
        "import sys\ninput = sys.stdin.readline\n\nN = int(input())\nA = list(map(int, input().split()))",
        language="python",
    )

    st.divider()

    # ── マイ・入力チートシートセクション ──────────────────
    st.subheader("マイ・入力チートシート")
    st.caption("自分でカスタマイズした入力パターンを追加・編集・削除できます。")

    render_add_form("input_cheatsheet_add_form", "input_cheatsheet", "➕ 新しい入力パターンを追加")
    st.divider()

    input_snippets = _fetch("input_cheatsheet")
    if not input_snippets:
        st.info("まだカスタムパターンが登録されていません。上のフォームから追加してみましょう。")
    else:
        st.markdown(f"**{len(input_snippets)} 件**")
        for snip in reversed(input_snippets):
            render_snippet_card(snip)

# ============================================================
# Tab 3: 典型アルゴリズム
# ============================================================
with tab3:
    # ── カテゴリ 1: N ≦ 20〜50 ─────────────────────────────────
    st.subheader("制約 N ≦ 20 〜 50 （指数・3乗の計算量）")

    with st.expander("🔍 1. bit全探索 / ループ", expanded=True):
        st.info(
            "2^N 通りの「選ぶ / 選ばない」を全列挙する。  \n"
            "計算量 **O(2^N × N)**。N ≤ 20 が実用上の目安。"
        )
        st.markdown("**【例題】** N個の整数からいくつか選んで、その和を S にすることができるか判定せよ。")
        st.markdown("**【入力例】** `N=3, S=10, A=[4, 1, 6]`  \n**【出力例】** `Yes`（4+6=10）")
        st.code("""\
N = 3
S = 10
A = [4, 1, 6]

ans = "No"
for bit in range(1 << N):
    subset_sum = 0
    for i in range(N):
        if bit >> i & 1:           # i ビット目が立っているか
            subset_sum += A[i]
    if subset_sum == S:
        ans = "Yes"
        break

print(ans)   # Yes
""", language="python")
        st.markdown("**応用: 全部分集合の合計の合計**")
        st.code("""\
arr = [4, 10, 1]

total = 0
for bit in range(1 << len(arr)):
    for i in range(len(arr)):
        if bit & (1 << i):
            total += arr[i]

print(total)   # 60
""", language="python")
        st.success("応用: 部分和判定・最小コスト選択・スケジューリング")

    with st.expander("🧮 2. bit DP / 集合 DP"):
        st.info(
            "訪問済みの頂点集合を bit で管理する DP。  \n"
            "巡回セールスマン問題（TSP）が典型。計算量 **O(2^N × N²)**。"
        )
        st.markdown("**【例題】** N都市をすべてちょうど1回ずつ訪問する最短経路の長さを求めよ（最短ハミルトン路）。")
        st.markdown("**【入力例】** `N=3, dist=[[0,2,8],[2,0,3],[8,3,0]]`  \n**【出力例】** `5`（0→1→2: 2+3=5）")
        st.code("""\
INF = float('inf')
N = 3
dist = [[0, 2, 8], [2, 0, 3], [8, 3, 0]]

# dp[bit][i] = 集合 bit を訪問済みで現在頂点 i にいるときの最小コスト
dp = [[INF] * N for _ in range(1 << N)]
dp[1][0] = 0    # 頂点0からスタート（bit=001）

for bit in range(1 << N):
    for i in range(N):
        if dp[bit][i] == INF:
            continue
        if not (bit & (1 << i)):    # i が未訪問なら skip
            continue
        for j in range(N):
            if bit & (1 << j):      # j が訪問済みなら skip
                continue
            nbit = bit | (1 << j)
            dp[nbit][j] = min(dp[nbit][j], dp[bit][i] + dist[i][j])

# 全都市訪問後の最小コスト（どの都市で終わってもよい）
ans = min(dp[(1 << N) - 1])
print(ans)   # 5
""", language="python")
        st.markdown("**集合DPの思考手順**")
        st.markdown(
            "1. `dp[bit][i]` の意味を「集合 bit を訪問済みで頂点 i にいる最小コスト」と定義する  \n"
            "2. 遷移: 未訪問の頂点 j に移動 → `dp[bit | (1<<j)][j]` を更新  \n"
            "3. 答えは `dp[(1<<N)-1][*]` の最小値"
        )
        st.success("応用: 巡回セールスマン問題・集合被覆・割り当て問題")

    with st.expander("🌐 3. Floyd-Warshall（ワーシャルフロイド）/ 行列 DP"):
        st.info(
            "全頂点間の最短経路を **O(N³)** で求める。  \n"
            "N ≦ 400 程度で有効。負辺があっても動作するが、負閉路があると正しく動かない。"
        )
        st.markdown("**【例題】** 全ての頂点対について、最短経路のコストを求めよ。")
        st.markdown("**【入力例】** `N=3, 辺(0-1:2), (1-2:3)`  \n**【出力例】** `5`（0から2への最短距離）")
        st.markdown("**ポイント: 中継頂点 k のループが最外側でなければならない**")
        st.code("""\
INF = float('inf')
N = 3
dist = [[INF] * N for _ in range(N)]
for i in range(N):
    dist[i][i] = 0

edges = [(0, 1, 2), (1, 2, 3)]
for u, v, w in edges:
    dist[u][v] = w
    dist[v][u] = w    # 無向グラフ

# ── ワーシャルフロイド本体（k → i → j の順が必須）──
for k in range(N):          # 中継頂点
    for i in range(N):      # 始点
        for j in range(N):  # 終点
            if dist[i][k] + dist[k][j] < dist[i][j]:
                dist[i][j] = dist[i][k] + dist[k][j]

ans = dist[0][2]
print(ans)   # 5  (0→1→2 = 2+3)
""", language="python")
        st.success("応用: 全点間最短路・経路の存在確認・負閉路検出")

    # ── カテゴリ 2: N ≦ 2000 ─────────────────────────────────────
    st.divider()
    st.subheader("制約 N ≦ 2000 （2乗の計算量）")

    with st.expander("📦 4. 二重ループ DP（ナップサック・部分和）"):
        st.info(
            "状態と遷移を持つ動的計画法。  \n"
            "部分和・01ナップサックが典型。計算量 **O(N × W)**。"
        )
        st.markdown("**【例題】** N個の品物（重さW, 価値V）から、重さの合計が W_max 以下になるように選んだときの価値の最大値を求めよ（ナップサック問題）。")
        st.markdown("**【入力例】** `W_max=10, Items=[(3,30),(4,50),(5,60)]`  \n**【出力例】** `110`（重さ4と5を選ぶ: 50+60=110）")
        st.code("""\
W_max = 10
items = [(3, 30), (4, 50), (5, 60)]

# dp[j] = 重量 j 以下で達成できる最大価値
dp = [0] * (W_max + 1)
for w_i, v_i in items:
    for j in reversed(range(w_i, W_max + 1)):   # 後ろから更新（01ナップサック）
        dp[j] = max(dp[j], dp[j - w_i] + v_i)

ans = dp[W_max]
print(ans)   # 110
""", language="python")
        st.markdown("**部分和問題（合計がちょうど S になる組み合わせがあるか）**")
        st.code("""\
N, S = 3, 10
A = [4, 1, 6]

dp = [False] * (S + 1)
dp[0] = True

for i in range(N):
    for j in reversed(range(S + 1)):    # 後ろから更新（01ナップサック）
        if dp[j] and j + A[i] <= S:
            dp[j + A[i]] = True

print("Yes" if dp[S] else "No")   # Yes
""", language="python")
        st.success("応用: コイン問題・LIS（最長増加部分列）・編集距離")

    with st.expander("🔀 5. バブルソート・基本的なソート"):
        st.info(
            "実用では `sorted()` / `.sort()` (Timsort, **O(N log N)**) を使う。  \n"
            "バブルソートは **O(N²)** だが「転倒数」の概念理解に役立つ。"
        )
        st.markdown("**【例題】** 学生のデータ（名前, 点数, 年齢）を、点数の降順、同点なら年齢の昇順に並べ替えよ。")
        st.markdown("**【入力例】** `[('Alice', 90, 20), ('Bob', 85, 22), ('Carol', 90, 18)]`  \n**【出力例】** `[('Carol', 90, 18), ('Alice', 90, 20), ('Bob', 85, 22)]`")
        st.code("""\
students = [("Alice", 90, 20), ("Bob", 85, 22), ("Carol", 90, 18)]

# 点数の降順、同点なら年齢の昇順
students.sort(key=lambda x: (-x[1], x[2]))

print(students)
# [('Carol', 90, 18), ('Alice', 90, 20), ('Bob', 85, 22)]
""", language="python")
        st.markdown("**バブルソートの概念コード（転倒数カウント付き）**")
        st.code("""\
arr = [5, 3, 1, 4, 2]
N = len(arr)
inv_count = 0   # 転倒数（何回スワップしたか）

for i in range(N):
    for j in range(N - 1 - i):
        if arr[j] > arr[j + 1]:
            arr[j], arr[j + 1] = arr[j + 1], arr[j]
            inv_count += 1

print(arr)        # [1, 2, 3, 4, 5]
print(inv_count)  # 転倒数
""", language="python")
        st.success("応用: 座標圧縮・転倒数・マージソートによる高速転倒数カウント")

    # ── カテゴリ 3: N ≦ 10^5〜10^6 ──────────────────────────────
    st.divider()
    st.subheader("制約 N ≦ 10⁵ 〜 10⁶ （N log N 以下の計算量）")

    with st.expander("🎯 6. 二分探索（配列・値域）"):
        st.info(
            "ソート済み配列内の検索 **O(log N)**。  \n"
            "「条件を満たす最小/最大値」もめぐる式二分探索で求められる。"
        )
        st.markdown("**【例題】** 条件「x² ≥ 100」を満たす最小の整数 x を求めよ（めぐる式二分探索）。")
        st.markdown("**【入力例】** `100`（目標値の二乗）  \n**【出力例】** `10`")
        st.code("""\
def ok(m: int) -> bool:
    return m * m >= 100   # x^2 >= 100 を満たす最小の x を探す

lo, hi = 0, 10**9
while lo + 1 < hi:
    mid = (lo + hi) // 2
    if ok(mid):
        hi = mid
    else:
        lo = mid

ans = hi
print(ans)   # 10  (10^2=100>=100, 9^2=81<100)
""", language="python")
        st.markdown("**bisect_left / bisect_right の使い分け**")
        st.markdown(
            "| 条件 | 使う関数 |\n"
            "|---|---|\n"
            "| `val < x`（x **未満**を数える） | `bisect_left` |\n"
            "| `val ≤ x`（x **以下**を数える） | `bisect_right` |\n"
            "| x **以上**の最小インデックス | `bisect_left` |\n"
            "| x **より大きい**最小インデックス | `bisect_right` |"
        )
        st.code("""\
import bisect

a = [1, 3, 3, 5, 7, 9]
x = 3
print(bisect.bisect_left(a, x))    # 1  (x 以上が始まる最左)
print(bisect.bisect_right(a, x))   # 3  (x より大きいが始まる最左)

# x の個数 = bisect_right - bisect_left
count = bisect.bisect_right(a, x) - bisect.bisect_left(a, x)
print(count)   # 2
""", language="python")
        st.success("応用: 最小化・最大化・N番目の値の探索")

    with st.expander("➕ 7. 累積和 / いもす法"):
        st.info(
            "区間和を **O(1)** で答える前処理 **O(N)**。  \n"
            "いもす法は「区間への加算クエリ」を O(N) で一括処理する。"
        )
        st.markdown("**【例題】** N日間の来店予約がある。「L日目からR日目まで人数が増える」というクエリをQ回処理した後の、各日の来店者数を求めよ。")
        st.markdown("**【入力例】** `N=5, クエリ: (1日目〜3日目に+1), (2日目〜4日目に+2)`  \n**【出力例】** `[0, 1, 3, 3, 2, 0]`（インデックス0は未使用、1〜5が各日）")
        st.code("""\
N = 5
queries = [(1, 3, 1), (2, 4, 2)]   # (L, R, x): L日目からR日目まで +x

imos = [0] * (N + 2)
for l, r, x in queries:
    imos[l] += x
    imos[r + 1] -= x

result = [0] * (N + 1)   # 1-indexed（result[i] が i 日目の来店者数）
for i in range(1, N + 1):
    result[i] = result[i - 1] + imos[i]

print(result)   # [0, 1, 3, 3, 2, 0]
""", language="python")
        st.markdown("**1次元累積和（区間和クエリ）**")
        st.code("""\
a = [3, 1, 4, 1, 5, 9, 2, 6]
N = len(a)

acc = [0] * (N + 1)
for i in range(N):
    acc[i + 1] = acc[i] + a[i]

# a[l..r-1] の和（0-indexed 半開区間）
def range_sum(l, r):
    return acc[r] - acc[l]

print(range_sum(2, 5))   # a[2]+a[3]+a[4] = 4+1+5 = 10
""", language="python")
        st.success("応用: 区間への一括加算・2次元いもす法・区間の重なり検出")

    with st.expander("🪟 8. 尺取り法（Two Pointers）"):
        st.info(
            "右端ポインタを進めながら、条件を破ったら左端を縮める。  \n"
            "条件を満たす連続部分列の個数や最大長を **O(N)** で求める。"
        )
        st.markdown("**【例題】** 長さNの数列Aがある。連続する部分列の和が K 以下となるような部分列の最長の長さを求めよ。")
        st.markdown("**【入力例】** `A=[1, 2, 3, 1, 2], K=4`  \n**【出力例】** `2`（例: [1,2] や [3,1]）")
        st.code("""\
A = [1, 2, 3, 1, 2]
K = 4
N = len(A)

left = 0
total = 0
max_len = 0

for right in range(N):
    total += A[right]
    while total > K:        # 条件を破ったら左端を縮める
        total -= A[left]
        left += 1
    max_len = max(max_len, right - left + 1)

ans = max_len
print(ans)   # 2
""", language="python")
        st.markdown("**応用: 合計が K 以下の区間の個数を数える**")
        st.code("""\
A = [1, 2, 3, 1, 2]
K = 4
N = len(A)

right = 0
total = 0
ans = 0

for left in range(N):
    while right < N and total + A[right] <= K:
        total += A[right]
        right += 1
    # [left, right) が条件を満たす → right - left 通り
    ans += (right - left)
    if right == left:
        right += 1
    else:
        total -= A[left]

print(ans)
""", language="python")
        st.success("応用: 最長部分列・合計が一定の区間カウント・スライディングウィンドウ")

    with st.expander("💰 9. グリーディ（貪欲法）"):
        st.info(
            "局所的に最善の選択を積み重ねることで全体最適を得る。  \n"
            "区間スケジューリングが典型例。"
        )
        st.markdown("**【例題】** N個の仕事（開始時間, 終了時間）がある。時間が重ならないように最大でいくつの仕事ができるか。")
        st.markdown("**【入力例】** `[(1,4), (3,5), (0,6), (5,7)]`  \n**【出力例】** `2`（(1,4) と (5,7) を選ぶ）")
        st.code("""\
intervals = [(1, 4), (3, 5), (0, 6), (5, 7)]

# 終了時刻の早い順にソートして貪欲に選ぶ
intervals.sort(key=lambda x: x[1])

count = 0
last_end = -1
for s, e in intervals:
    if s >= last_end:       # 直前の区間と重ならない
        count += 1
        last_end = e

ans = count
print(ans)   # 2
""", language="python")
        st.markdown("**コイン問題（最少枚数で両替）**")
        st.code("""\
coins = [500, 100, 50, 10, 5, 1]
amount = 1234
result = []
for c in coins:
    result.append(amount // c)
    amount %= c
print(result)   # [2, 2, 0, 3, 0, 4]  ← 各コインの枚数
""", language="python")
        st.success("応用: 活動選択問題・会議室割り当て・最小コスト問題")

    with st.expander("🌲 10. BIT（Fenwick Tree）/ セグメント木"):
        st.info(
            "一点更新と区間和取得をどちらも **O(log N)** で行うデータ構造。  \n"
            "BIT（Binary Indexed Tree）は実装が軽量で、転倒数・順位クエリに頻出。"
        )
        st.markdown("**【例題】** 長さNの数列の「i番目にxを足す」「1番目からi番目までの和を求める」クエリを高速に処理せよ。")
        st.markdown("**【入力例】** `A=[3,1,4,1,5,9,2,6]`、add(3, 10) 後に range_query(3, 6) を求めよ  \n**【出力例】** `29`（(4+10)+1+5+9=29）")
        st.markdown("**BIT (1-indexed) の実装**")
        st.code("""\
class BIT:
    def __init__(self, n):
        self.n = n
        self.tree = [0] * (n + 1)

    def add(self, i, x):
        while i <= self.n:
            self.tree[i] += x
            i += i & (-i)       # 最下位ビットだけ立てたもの

    def query(self, i):
        s = 0
        while i > 0:
            s += self.tree[i]
            i -= i & (-i)
        return s

    def range_query(self, l, r):
        return self.query(r) - self.query(l - 1)


A = [3, 1, 4, 1, 5, 9, 2, 6]
bit = BIT(len(A))
for i, x in enumerate(A, start=1):
    bit.add(i, x)

print(bit.range_query(3, 6))   # 4+1+5+9 = 19
bit.add(3, 10)                  # 3番目に 10 を加算
ans = bit.range_query(3, 6)
print(ans)                      # (4+10)+1+5+9 = 29
""", language="python")
        st.success("応用: 転倒数カウント・動的な区間和・座標圧縮との組み合わせ")

    # ── カテゴリ 4: 数学・巨大な制約 ─────────────────────────────
    st.divider()
    st.subheader("数学・巨大な制約")

    with st.expander("⚡ 11. 繰り返し二乗法"):
        st.info(
            "a^n mod m を **O(log n)** で計算する。  \n"
            "Python では組み込みの `pow(a, n, mod)` が最速で推奨。"
        )
        st.markdown("**【例題】** a^n を mod M で割った余りを求めよ。")
        st.markdown("**【入力例】** `a=2, n=100, M=10^9+7`  \n**【出力例】** `976371285`")
        st.code("""\
a, n, mod = 2, 100, 10**9 + 7
ans = pow(a, n, mod)   # 組み込み関数で O(log n)
print(ans)             # 976371285
""", language="python")
        st.markdown("**手書き実装（仕組みの理解用）**")
        st.code("""\
def mod_pow(base: int, exp: int, mod: int) -> int:
    result = 1
    base %= mod
    while exp > 0:
        if exp & 1:             # exp の最下位ビットが 1 なら掛ける
            result = result * base % mod
        base = base * base % mod
        exp >>= 1               # exp を右に 1 ビットシフト
    return result

print(mod_pow(2, 100, 10**9 + 7))   # 976371285
""", language="python")
        st.markdown("**よく使うパターン: 組み合わせ数 nCr mod p**")
        st.code("""\
MOD = 10**9 + 7

def modinv(a, mod):
    return pow(a, mod - 2, mod)   # フェルマーの小定理（mod が素数のとき）

def comb(n, r, mod):
    if r < 0 or r > n:
        return 0
    num = den = 1
    for i in range(r):
        num = num * (n - i) % mod
        den = den * (i + 1) % mod
    return num * modinv(den, mod) % mod

print(comb(10, 3, MOD))   # 120
""", language="python")
        st.success("応用: 組み合わせ数の計算・逆元・行列の累乗")

    with st.expander("🔢 12. 約数列挙 / 素因数分解"):
        st.info(
            "O(√N) で約数や素因数を列挙する。  \n"
            "N が 10^12 程度でも十分に高速。"
        )
        st.markdown("**【例題】** 整数 N の素因数分解を行い、それぞれの素因数とその個数を出力せよ。")
        st.markdown("**【入力例】** `N=360`  \n**【出力例】** `[(2, 3), (3, 2), (5, 1)]`（2³ × 3² × 5 = 360）")
        st.code("""\
def factorize(N: int) -> list:
    factors = []
    d = 2
    while d * d <= N:
        if N % d == 0:
            cnt = 0
            while N % d == 0:
                cnt += 1
                N //= d
            factors.append((d, cnt))
        d += 1
    if N > 1:
        factors.append((N, 1))
    return factors

ans = factorize(360)
print(ans)   # [(2, 3), (3, 2), (5, 1)]  → 2³ × 3² × 5
""", language="python")
        st.markdown("**約数の全列挙 O(√N)**")
        st.code("""\
def get_divisors(N: int) -> list:
    divisors = []
    i = 1
    while i * i <= N:
        if N % i == 0:
            divisors.append(i)
            if i != N // i:
                divisors.append(N // i)
        i += 1
    divisors.sort()
    return divisors

print(get_divisors(12))   # [1, 2, 3, 4, 6, 12]
""", language="python")
        st.markdown("**素数判定（O(√N)）と エラトステネスの篩（O(N log log N)）**")
        st.code("""\
def is_prime(n: int) -> bool:
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True

def sieve(N: int) -> list:
    is_p = [True] * (N + 1)
    is_p[0] = is_p[1] = False
    i = 2
    while i * i <= N:
        if is_p[i]:
            j = i * i
            while j <= N:
                is_p[j] = False
                j += i
        i += 1
    return [i for i in range(2, N + 1) if is_p[i]]

print(sieve(30))   # [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]
""", language="python")
        st.success("応用: 約数の個数・最大公約数・素数テーブル")

# ============================================================
# Tab 5: リンク集
# ============================================================
with tab5:
    st.subheader("便利リンク集")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### AtCoder 公式")
        st.link_button("🏠 AtCoder トップ",          "https://atcoder.jp/",           use_container_width=True)
        st.link_button("📝 コンテスト一覧",           "https://atcoder.jp/contests/",  use_container_width=True)
        st.markdown("#### 学習リソース")
        st.link_button("📖 AtCoder 入門の手引き",     "https://atcoder.jp/posts/261",  use_container_width=True)
        st.link_button("📘 競プロ典型 90 問 (GitHub)", "https://github.com/E869120/kyopro-educational-90", use_container_width=True)
    with col2:
        st.markdown("#### 問題検索・分析")
        st.link_button("🔎 AtCoder Problems",         "https://kenkoooo.com/atcoder/",          use_container_width=True)
        st.link_button("📊 AtCoder Problems Heatmap", "https://kenkoooo.com/atcoder/#/table/",  use_container_width=True)
        st.markdown("#### ライブラリ・ツール")
        st.link_button("📦 Library Checker",          "https://judge.yosupo.jp/",               use_container_width=True)
        st.link_button("🐍 AC Library Python",        "https://github.com/not522/ac-library-python", use_container_width=True)

    st.divider()
    st.markdown("#### Visualizer / デバッグ支援")
    c1, c2, c3 = st.columns(3)
    c1.link_button("🌐 Graph Editor",    "https://csacademy.com/app/graph_editor/", use_container_width=True)
    c2.link_button("📐 Wolfram Alpha",   "https://www.wolframalpha.com/",           use_container_width=True)
    c3.link_button("⏱️ Big-O Cheat Sheet", "https://www.bigocheatsheet.com/",       use_container_width=True)

# ============================================================
# Tab 4: マイ・スニペット
# ============================================================
with tab4:
    st.subheader("マイ・スニペット")
    st.caption("自分が重要と思ったコードやメモを保存・編集・削除できます。")

    render_add_form("my_snippet_add_form", "my_snippet", "➕ 新しいスニペットを追加")
    st.divider()

    my_snippets = _fetch("my_snippet")
    if not my_snippets:
        st.info("まだスニペットが保存されていません。上のフォームから追加してみましょう。")
    else:
        st.markdown(f"**{len(my_snippets)} 件のスニペット**")
        for snip in reversed(my_snippets):
            render_snippet_card(snip)
