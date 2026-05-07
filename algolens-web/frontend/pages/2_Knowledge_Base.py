import pandas as pd
import streamlit as st

st.set_page_config(page_title="Knowledge Base | AlgoLens", page_icon="📚", layout="wide")
st.title("📚 Knowledge Base")
st.caption("競技プログラミングで使える定石・スニペット集")

tab1, tab2, tab3, tab4 = st.tabs(["解法チートシート", "入力チートシート", "典型アルゴリズム", "リンク集"])

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

    st.subheader("よくある TLE パターン")
    st.warning(
        "- `list.index()` や `in list` を繰り返す → `set` や `dict` に変える  \n"
        "- `str` を `+=` で連結するループ → `''.join(list)` にする  \n"
        "- 再帰が深い → `sys.setrecursionlimit` を増やすか BFS/反復に変える"
    )

# ============================================================
# Tab 2: 入力チートシート
# ============================================================
with tab2:
    st.subheader("Python 標準入力パターン")
    st.info("AtCoder の入力形式別スニペット。コピペして即使用できます。")

    snippets = [
        ("整数 1 つ",                   "n = int(input())"),
        ("スペース区切り整数（2 変数）", "a, b = map(int, input().split())"),
        ("スペース区切り整数リスト",     "a = list(map(int, input().split()))"),
        ("N 行の整数（1 列）",           "a = [int(input()) for _ in range(n)]"),
        ("N 行・スペース区切り（2D）",   "data = [list(map(int, input().split())) for _ in range(n)]"),
        ("グリッド（文字）",             "grid = [input() for _ in range(h)]"),
        ("グリッド（整数）",             "grid = [list(map(int, input().split())) for _ in range(h)]"),
        ("1 行を文字のリストに",         "chars = list(input())"),
    ]
    for label, code in snippets:
        st.markdown(f"**{label}**")
        st.code(code, language="python")

    st.subheader("高速入出力（大量 I/O 時）")
    st.code(
        "import sys\ninput = sys.stdin.readline\n\nn = int(input())\na = list(map(int, input().split()))",
        language="python",
    )

# ============================================================
# Tab 3: 典型アルゴリズム
# ============================================================
with tab3:
    st.subheader("典型アルゴリズム スニペット集")

    with st.expander("🔍 bit 全探索", expanded=True):
        st.info("N 個の要素から部分集合を全て列挙する。計算量 O(2^N × N)。N ≤ 20 が目安。")
        st.code(
            """\
n = 4
items = [1, 2, 3, 4]

for bit in range(1 << n):       # 0 から 2^n - 1
    selected = []
    for i in range(n):
        if bit >> i & 1:        # i ビット目が立っているか
            selected.append(items[i])
    print(selected)
""",
            language="python",
        )
        st.success("応用: 部分和判定・最小コスト選択・スケジューリング")

    with st.expander("🎯 二分探索（bisect）"):
        st.info("ソート済みリストへの高速検索 O(log N)。「答えを二分探索する」パターンも重要。")
        st.code(
            """\
import bisect

a = [1, 3, 5, 7, 9]

# x 以上の最小インデックス
idx = bisect.bisect_left(a, 5)       # → 2

# x より大きい最小インデックス
idx = bisect.bisect_right(a, 5)      # → 3

# 「条件を満たす最小の x」を二分探索
def ok(x):
    return x * x >= 25               # 判定条件

lo, hi = 0, 10**9
while lo < hi:
    mid = (lo + hi) // 2
    if ok(mid):
        hi = mid
    else:
        lo = mid + 1
print(lo)   # → 5
""",
            language="python",
        )
        st.success("応用: 最小化・最大化・lower_bound / upper_bound")

    with st.expander("➕ 累積和"):
        st.info("区間和クエリを O(1) で答える前処理。構築は O(N)。")
        st.code(
            """\
a = [3, 1, 4, 1, 5, 9, 2, 6]
n = len(a)

# 構築（1-indexed）
acc = [0] * (n + 1)
for i in range(n):
    acc[i + 1] = acc[i] + a[i]

# a[l..r-1] の和（0-indexed 半開区間）
def range_sum(l, r):
    return acc[r] - acc[l]

print(range_sum(2, 5))   # a[2]+a[3]+a[4] = 4+1+5 = 10
""",
            language="python",
        )
        st.success("応用: 2D 累積和・いもす法・部分列の最大和")

    with st.expander("📦 DP（部分和問題）"):
        st.info("N 個の整数から何個か選んで和が W になるか判定。O(N × W)。")
        st.code(
            """\
a = [1, 2, 3, 4, 5]
W = 9
n = len(a)

# 2D DP
dp = [[False] * (W + 1) for _ in range(n + 1)]
dp[0][0] = True

for i in range(n):
    for w in range(W + 1):
        if not dp[i][w]:
            continue
        dp[i + 1][w] = True              # a[i] を選ばない
        if w + a[i] <= W:
            dp[i + 1][w + a[i]] = True   # a[i] を選ぶ

print(dp[n][W])   # True（例: 4+5=9）

# メモリ最適化（1D DP、後ろから更新）
dp1d = [False] * (W + 1)
dp1d[0] = True
for x in a:
    for w in range(W, x - 1, -1):
        if dp1d[w - x]:
            dp1d[w] = True
print(dp1d[W])
""",
            language="python",
        )
        st.success("応用: ナップサック問題・コイン問題・LIS")

    with st.expander("🗺️ 実装（dx/dy配列を使った2次元グリッドBFS）"):
        st.info("マス目上の移動・BFS最短距離など、隣接4マスを処理する定番実装。")
        st.code(
            """\
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
""",
            language="python",
        )
        st.success("応用: 迷路の最短距離・連結成分カウント・多始点BFS")

    with st.expander("🗂️ ハッシュテーブル（Counter / defaultdict）"):
        st.info("要素の出現回数を素早く集計する。辞書の存在確認は平均 O(1)。")
        st.code(
            """\
from collections import Counter, defaultdict

# Counter: 頻度カウント
s = "abracadabra"
cnt = Counter(s)
print(cnt)                  # Counter({'a': 5, 'b': 2, 'r': 2, ...})
print(cnt['a'])             # 5
print(cnt.most_common(2))   # [('a', 5), ('b', 2)]

# defaultdict: KeyError が出ないグラフ構築
graph = defaultdict(list)
for u, v in [(1, 2), (1, 3), (2, 4)]:
    graph[u].append(v)
    graph[v].append(u)

# 辞書で O(1) 存在確認
seen = {}
for x in [3, 1, 4, 1, 5, 9, 2, 6, 5]:
    if x in seen:
        print(f"{x} は重複")
    seen[x] = True
""",
            language="python",
        )
        st.success("応用: 重複検出・グラフ構築・文字頻度分析")

    with st.expander("💰 貪欲法（区間スケジューリング）"):
        st.info("局所的に最善の選択を繰り返すことで全体最適が得られる問題に使う。")
        st.code(
            """\
# 区間スケジューリング（終了時刻でソートして貪欲）
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

# コインの両替
coins = [500, 100, 50, 10, 5, 1]
amount = 1234
result = []
for c in coins:
    result.append(amount // c)
    amount %= c
print(result)   # [2, 2, 0, 3, 0, 4]
""",
            language="python",
        )
        st.success("応用: 活動選択問題・コイン問題・会議室割り当て")

    with st.expander("🔢 ソート（lambda を使った複数キーソート）"):
        st.info("タプルや複数条件での並び替え。Python の sorted() / .sort() は安定ソート（Timsort, O(N log N)）。")
        st.code(
            """\
# 基本ソート
arr = [3, 1, 4, 1, 5, 9]
print(sorted(arr))               # 昇順
print(sorted(arr, reverse=True)) # 降順

# 複数キーソート（1st: スコア降順、2nd: 年齢昇順）
students = [("Alice", 90, 20), ("Bob", 85, 22), ("Carol", 90, 19)]
students.sort(key=lambda x: (-x[1], x[2]))
print(students)
# [('Carol', 90, 19), ('Alice', 90, 20), ('Bob', 85, 22)]

# 絶対値でソート
arr2 = [-5, 3, -1, 4, -2]
print(sorted(arr2, key=abs))   # [-1, -2, 3, 4, -5]

# 文字列を長さでソート
words = ["banana", "apple", "cherry", "fig"]
print(sorted(words, key=len))  # ['fig', 'apple', 'banana', 'cherry']
""",
            language="python",
        )
        st.success("応用: 辞書順・複合条件ランキング・座標圧縮")

    with st.expander("🔍 めぐる式二分探索"):
        st.info("「条件を満たす最小/最大値」を O(log N) で求める。単調性があれば何でも使える。")
        st.code(
            """\
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

# 「True になる最大の m」を探す場合（逆向き）
def ok2(m: int) -> bool:
    return m * m <= 10

lo2, hi2 = 0, 10**9
while lo2 + 1 < hi2:
    mid = (lo2 + hi2) // 2
    if ok2(mid):
        lo2 = mid
    else:
        hi2 = mid
print(lo2)   # 3  (3^2=9<=10, 4^2=16>10)
""",
            language="python",
        )
        st.success("応用: 最小化・最大化・巡回セールスマン緩和・木の直径")

# ============================================================
# Tab 4: リンク集
# ============================================================
with tab4:
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
