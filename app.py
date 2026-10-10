import os
import time
from typing import Any

import pandas as pd
import streamlit as st
from pixivpy3 import AppPixivAPI


st.set_page_config(page_title="Pixiv 태그 작품 정렬기", page_icon="🔎", layout="wide")
st.title("Pixiv 태그 작품 정렬기")
st.caption("태그 검색 결과를 수집해 조회수·북마크순으로 정렬합니다.")

# Optional access gate. Configure APP_PASSWORD in Streamlit secrets for hosted use.
app_password = os.environ.get("APP_PASSWORD", "").strip()
if app_password:
    if not st.session_state.get("authenticated", False):
        with st.form("access_gate"):
            entered = st.text_input("앱 접근 비밀번호", type="password")
            submitted = st.form_submit_button("접속")
        if submitted:
            if entered == app_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
        st.stop()

st.warning(
    "이 앱은 PixivPy3라는 비공식 라이브러리를 사용합니다. "
    "Pixiv 측의 변경이나 제한으로 검색이 실패할 수 있으며, 모든 작품을 수집할 수 있다고 보장하지 않습니다. "
    "요청 제한을 우회하지 말고 오류가 나면 검색을 중단하세요."
)


def get_value(obj: Any, key: str, default=None):
    """Read a field from either a PixivPy3 model or a dictionary."""
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
    result = []
    for tag in raw_tags:
        name = get_value(tag, "name")
        if name:
            result.append(str(name))
    return ", ".join(result)


def make_row(illust):
    illust_id = get_value(illust, "id")
    user = get_value(illust, "user")
    user_name = get_value(user, "name", "") or ""
    title = get_value(illust, "title", "") or ""
    create_date = get_value(illust, "create_date", "") or ""

    # Pixiv API models commonly expose total_view and total_bookmarks.
    # Keep unavailable values as None rather than pretending they are zero.
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


def search_tag(tag: str, max_items: int, delay_seconds: float, refresh_token: str,
               exact_tag: bool, progress, status):
    api = AppPixivAPI()
    api.auth(refresh_token=refresh_token)

    target = "exact_match_for_tags" if exact_tag else "partial_match_for_tags"
    offset = 0
    rows = []
    seen_ids = set()
    page_size_hint = 30

    while len(rows) < max_items:
        status.write(f"검색 요청 중… 수집된 작품: {len(rows):,}")
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


with st.sidebar:
    st.header("검색 설정")
    tag = st.text_input("Pixiv 태그", placeholder="예: オリジナル")
    exact_tag = st.checkbox("태그 완전 일치", value=False)
    st.caption("AI 생성 작품 필터는 이 버전에서 별도 제공하지 않습니다.")
    max_items = st.select_slider(
        "최대 수집 작품 수",
        options=[30, 60, 120, 300, 600, 1000],
        value=120,
        help="검색 API의 한도와 응답에 따라 실제 수집량은 이보다 적을 수 있습니다.",
    )
    delay_seconds = st.slider(
        "페이지 요청 간격(초)",
        min_value=1.0,
        max_value=5.0,
        value=2.0,
        step=0.5,
        help="요청을 빠르게 반복하지 않도록 간격을 둡니다.",
    )
    run_search = st.button("검색 시작", type="primary", use_container_width=True)

    st.divider()
    st.subheader("인증")
    st.caption(
        "Pixiv refresh token을 환경변수 PIXIV_REFRESH_TOKEN에 설정하세요. "
        "토큰을 채팅, 코드 저장소 또는 공개된 화면에 올리지 마세요."
    )

token = os.environ.get("PIXIV_REFRESH_TOKEN", "").strip()
if not token:
    try:
        token = str(st.secrets.get("PIXIV_REFRESH_TOKEN", "")).strip()
    except Exception:
        token = ""

if "results_df" not in st.session_state:
    st.session_state.results_df = pd.DataFrame()

if run_search:
    if not tag.strip():
        st.error("검색할 태그를 입력하세요.")
    elif not token:
        st.error(
            "PIXIV_REFRESH_TOKEN 환경변수가 없습니다. "
            "아래 README의 인증 설정 안내를 확인한 뒤 앱을 다시 실행하세요."
        )
    else:
        progress = st.progress(0.0)
        status = st.empty()
        try:
            with st.spinner("Pixiv 검색 결과를 수집하고 있습니다…"):
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
                st.info("작품이 반환되지 않았습니다. 태그나 인증 설정을 확인하세요.")
            else:
                st.success(f"수집 완료: {len(df):,}개 작품")
        except Exception as exc:
            st.error(
                "검색 중 오류가 발생했습니다. 인증 상태, 네트워크, PixivPy3 호환성을 확인하세요. "
                "접근 제한이 발생했다면 반복 요청하지 말고 잠시 후 공식 사이트에서 상태를 확인하세요."
            )
            st.code(f"{type(exc).__name__}: {exc}")

df = st.session_state.results_df

if not df.empty:
    st.subheader("검색 결과")
    sort_choice = st.selectbox(
        "정렬 기준",
        ["조회수 높은 순", "북마크 많은 순", "최신순", "제목순"],
    )

    sort_map = {
        "조회수 높은 순": ("조회수", False),
        "북마크 많은 순": ("북마크", False),
        "최신순": ("게시일", False),
        "제목순": ("제목", True),
    }
    column, ascending = sort_map[sort_choice]
    # Missing metrics stay missing and sort to the bottom.
    display_df = df.sort_values(
        by=column, ascending=ascending, na_position="last", kind="stable"
    ).reset_index(drop=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("수집 작품", f"{len(display_df):,}")
    c2.metric("조회수 데이터 있음", f"{display_df['조회수'].notna().sum():,}")
    c3.metric("북마크 데이터 있음", f"{display_df['북마크'].notna().sum():,}")

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "작품 링크": st.column_config.LinkColumn("작품 링크", display_text="Pixiv 열기"),
            "작가 링크": st.column_config.LinkColumn("작가 링크", display_text="작가 페이지"),
            "조회수": st.column_config.NumberColumn("조회수", format="%d"),
            "북마크": st.column_config.NumberColumn("북마크", format="%d"),
        },
    )

    csv_bytes = display_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "CSV 다운로드",
        data=csv_bytes,
        file_name="pixiv_tag_results.csv",
        mime="text/csv",
    )
else:
    st.info("왼쪽에서 태그와 수집 범위를 설정한 뒤 검색을 시작하세요.")

st.caption(
    "이 도구는 작품 메타데이터만 다루며 이미지 파일을 일괄 다운로드하지 않습니다. "
    "Pixiv의 이용약관과 접근 정책을 준수해 개인적으로 사용하세요."
)
