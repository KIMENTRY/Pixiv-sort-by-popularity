import os
import time
from typing import Any

import pandas as pd
import streamlit as st
from pixivpy3 import AppPixivAPI


st.set_page_config(
    page_title="Pixiv 태그 작품 정렬기",
    page_icon="🔎",
    layout="centered",  # 모바일에 더 적합
    initial_sidebar_state="collapsed",
)

# 모바일 반응형 CSS
st.markdown("""
<style>
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max-width: 720px;
    }
    div[data-testid="stMetric"] {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 8px;
    }
</style>
""", unsafe_allow_html=True)

st.title("🔎 Pixiv 태그 작품 정렬기")
st.caption("태그 검색 → 조회수·북마크순 정렬 · CSV 다운로드")

# ─── 앱 접근 비밀번호 ──────────────────────────────
app_password = os.environ.get("APP_PASSWORD", "").strip()
if not app_password:
    try:
        app_password = str(st.secrets.get("APP_PASSWORD", "")).strip()
    except Exception:
        app_password = ""

if app_password:
    if not st.session_state.get("authenticated", False):
        with st.form("access_gate"):
            st.subheader("🔐 접속 비밀번호")
            entered = st.text_input("비밀번호", type="password")
            submitted = st.form_submit_button("접속", use_container_width=True)
        if submitted:
            if entered == app_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
        st.stop()

st.warning(
    "비공식 라이브러리(PixivPy3)를 사용합니다. "
    "Pixiv 정책 변경으로 검색이 실패할 수 있으며, 요청 제한을 우회하지 마세요."
)

# ─── 유틸 함수 ─────────────────────────────────────
def get_value(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def as_int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_tags(illust):
    raw_tags = get_value(illust, "tags", []) or []
    names = []
    for tag in raw_tags:
        name = get_value(tag, "name")
        if name:
            names.append(str(name))
    return ", ".join(names)


def make_row(illust):
    illust_id = get_value(illust, "id")
    user = get_value(illust, "user")
    user_name = get_value(user, "name", "") or ""
    title = get_value(illust, "title", "") or ""
    create_date = get_value(illust, "create_date", "") or ""

    views = as_int_or_none(get_value(illust, "total_view"))
    bookmarks = as_int_or_none(get_value(illust, "total_bookmarks"))

    return {
        "작품 ID": illust_id,
        "제목": title,
        "작가": user_name,
        "조회수": views,
        "북마크": bookmarks,
        "게시일": str(create_date),
        "태그": get_tags(illust),
        "작품 링크": f"https://www.pixiv.net/artworks/{illust_id}" if illust_id else "",
        "작가 링크": (
            f"https://www.pixiv.net/users/{get_value(user, 'id')}"
            if get_value(user, "id") else ""
        ),
    }


def search_tag(tag: str, max_items: int, delay_seconds: float,
               refresh_token: str, exact_tag: bool, progress, status):
    api = AppPixivAPI()
    api.auth(refresh_token=refresh_token)

    target = "exact_match_for_tags" if exact_tag else "partial_match_for_tags"
    offset = 0
    rows = []
    seen_ids = set()
    page_size_hint = 30

    while len(rows) < max_items:
        status.write(f"검색 중… 현재 {len(rows):,}개 수집")
        result = api.search_illust(
            word=tag,
            search_target=target,
            sort="date_desc",
            offset=offset,
        )

        illustrations = get_value(result, "illusts", []) or []
        if not illustrations:
            break

        new_count = 0
        for illust in illustrations:
            row = make_row(illust)
            work_id = row["작품 ID"]
            if work_id is None or work_id in seen_ids:
                continue
            seen_ids.add(work_id)
            rows.append(row)
            new_count += 1
            if len(rows) >= max_items:
                break

        progress.progress(min(len(rows) / max_items, 1.0))

        if len(illustrations) < page_size_hint or new_count == 0:
            break

        offset += len(illustrations)
        time.sleep(delay_seconds)

    return pd.DataFrame(rows)


# ─── 검색 설정 (메인 화면) ─────────────────────────
with st.expander("🔍 검색 설정", expanded=True):
    tag = st.text_input("Pixiv 태그", placeholder="예: オリジナル / 女の子")
    col1, col2 = st.columns(2)
    with col1:
        exact_tag = st.checkbox("태그 완전 일치", value=False)
    with col2:
        max_items = st.select_slider(
            "최대 수집 수",
            options=[30, 60, 120, 300, 600],
            value=120,
        )
    delay_seconds = st.slider("요청 간격(초)", 1.0, 4.0, 2.0, 0.5)
    run_search = st.button("검색 시작", type="primary", use_container_width=True)

# ─── 토큰 확인 ─────────────────────────────────────
token = os.environ.get("PIXIV_REFRESH_TOKEN", "").strip()
if not token:
    try:
        token = str(st.secrets.get("PIXIV_REFRESH_TOKEN", "")).strip()
    except Exception:
        token = ""

if "results_df" not in st.session_state:
    st.session_state.results_df = pd.DataFrame()

# ─── 검색 실행 ─────────────────────────────────────
if run_search:
    if not tag.strip():
        st.error("검색할 태그를 입력하세요.")
    elif not token:
        st.error(
            "PIXIV_REFRESH_TOKEN이 없습니다.\n"
            "Streamlit Secrets에 토큰을 설정한 뒤 앱을 다시 실행하세요."
        )
    else:
        progress = st.progress(0.0)
        status = st.empty()
        try:
            with st.spinner("Pixiv에서 작품을 수집하고 있습니다…"):
                df = search_tag(
                    tag=tag.strip(),
                    max_items=int(max_items),
                    delay_seconds=float(delay_seconds),
                    refresh_token=token,
                    exact_tag=exact_tag,
                    progress=progress,
                    status=status,
                )
            st.session_state.results_df = df
            status.empty()
            progress.empty()
            if df.empty:
                st.info("작품이 반환되지 않았습니다. 태그나 인증을 확인하세요.")
            else:
                st.success(f"✅ 수집 완료: {len(df):,}개 작품")
        except Exception as exc:
            st.error(
                "검색 중 오류가 발생했습니다.\n"
                "• 토큰이 유효한지 확인하세요\n"
                "• 네트워크/Pixiv 접속 상태를 확인하세요\n"
                "• 403/429 오류면 잠시 후 다시 시도하세요"
            )
            with st.expander("오류 상세"):
                st.code(f"{type(exc).__name__}: {exc}")

# ─── 결과 표시 ─────────────────────────────────────
df = st.session_state.results_df

if not df.empty:
    st.subheader("📊 검색 결과")

    sort_choice = st.selectbox(
        "정렬 기준",
        ["조회수 높은 순", "북마크 많은 순", "최신순", "제목순"],
        key="sort_choice",
    )

    sort_map = {
        "조회수 높은 순": ("조회수", False),
        "북마크 많은 순": ("북마크", False),
        "최신순": ("게시일", False),
        "제목순": ("제목", True),
    }
    column, ascending = sort_map[sort_choice]
    display_df = df.sort_values(
        by=column, ascending=ascending, na_position="last", kind="stable"
    ).reset_index(drop=True)

    m1, m2, m3 = st.columns(3)
    m1.metric("수집 작품", f"{len(display_df):,}")
    m2.metric("조회수 있음", f"{display_df['조회수'].notna().sum():,}")
    m3.metric("북마크 있음", f"{display_df['북마크'].notna().sum():,}")

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "작품 링크": st.column_config.LinkColumn("작품 링크", display_text="열기"),
            "작가 링크": st.column_config.LinkColumn("작가 링크", display_text="작가"),
            "조회수": st.column_config.NumberColumn("조회수", format="%d"),
            "북마크": st.column_config.NumberColumn("북마크", format="%d"),
        },
        height=480,
    )

    csv_bytes = display_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 CSV 다운로드",
        data=csv_bytes,
        file_name="pixiv_tag_results.csv",
        mime="text/csv",
        use_container_width=True,
    )
else:
    st.info("위에서 태그를 입력하고 **검색 시작**을 누르세요.")

st.caption(
    "작품 메타데이터만 다루며 이미지를 다운로드하지 않습니다. "
    "Pixiv 이용약관과 요청 제한을 준수해 개인 용도로만 사용하세요."
)