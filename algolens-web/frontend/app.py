import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="AlgoLens", page_icon="🔍", layout="wide")

st.title("🔍 AlgoLens")
st.caption("AtCoder 学習最適化ダッシュボード")

st.markdown("""
### ナビゲーション
左サイドバーからページを選んでください。

| ページ | 内容 |
|--------|------|
| 📊 Analysis | 弱点分析・タグ別 AC 率グラフ |
| 📋 Problems | 問題一覧・難易度フィルター |
| 🔄 Sync | AtCoder からデータを同期 |
""")

st.info("初回利用時は **Sync** ページでユーザー登録と提出データの同期を行ってください。")
