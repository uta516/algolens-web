import requests
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Sync | AlgoLens", page_icon="🔄", layout="wide")
st.title("🔄 データ同期")
st.caption("ユーザー登録と AtCoder Problems からのデータ取り込みを行います。")

def api_post(path: str, json: dict | None = None) -> requests.Response:
    return requests.post(f"{API_BASE}{path}", json=json, timeout=60)

st.header("1. ユーザー登録")
with st.form("register_form"):
    reg_username = st.text_input("AtCoder ユーザー名", placeholder="例: tourist")
    submitted = st.form_submit_button("登録", type="primary")
    if submitted and reg_username.strip():
        try:
            resp = api_post("/users/", json={"atcoder_username": reg_username.strip()})
            if resp.status_code in [201, 409]:
                st.success(f"✅ {reg_username} の登録・確認が完了しました。")
                st.session_state["username"] = reg_username.strip()
            else:
                st.error(f"エラー: {resp.text}")
        except:
            st.error("バックエンドに接続できません。")

st.divider()

st.header("2. 問題マスタ同期")
if st.button("問題マスタを同期", type="primary"):
    with st.spinner("同期中..."):
        try:
            resp = api_post("/sync/problems")
            if resp.ok:
                st.success(f"✅ 同期完了: {resp.json()['upserted']}件更新")
            else:
                st.error("同期失敗")
        except:
            st.error("接続エラー")

st.divider()

# --- ここが新しく追加したかったタグ同期セクション ---
st.header("3. タグ同期")
st.markdown("問題にアルゴリズムタグ（DP、二分探索など）を付与します。APIから取得できない場合は、タイトルや難易度からAI（ロジック）が推定します。")
if st.button("タグを同期", type="primary"):
    with st.spinner("タグデータを付与中..."):
        try:
            resp = api_post("/sync/tags")
            if resp.ok:
                data = resp.json()
                st.success(f"✅ タグ同期完了！ (API更新: {data['api_updated']}件 / 推定付与: {data['seed_updated']}件)")
            else:
                st.error("タグ同期に失敗しました。")
        except:
            st.error("バックエンドに接続できません。")

st.divider()

st.header("4. 提出データ同期")
sync_username = st.text_input("同期するユーザー名", value=st.session_state.get("username", ""))
if st.button("提出データを同期", type="primary"):
    if sync_username:
        with st.spinner("取得中..."):
            try:
                resp = api_post(f"/sync/submissions/{sync_username}")
                if resp.ok:
                    st.success(f"✅ 提出データ同期完了！")
                else:
                    st.error("同期失敗")
            except:
                st.error("接続エラー")