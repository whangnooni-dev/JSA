"""한국은행 금융경제 스냅샷 대시보드.

실행: uv run streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard import data  # noqa: E402

# 범주형 팔레트: 색은 지표(컬럼)의 원래 순서에 고정되고, 표시 여부와 무관하다.
PALETTE = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
}
PERIODS = {"1년": 1, "3년": 3, "5년": 5, "10년": 10, "전체": None}
SOURCE = "출처: 한국은행 금융경제 스냅샷 (snapshot.bok.or.kr), FinanceDataReader"

st.set_page_config(page_title="한국은행 경제지표", page_icon="📈", layout="wide")


@st.cache_data(ttl=3600, show_spinner="지표 목록을 불러오는 중…")
def load_indicators() -> list[data.Indicator]:
    return data.load_indicators()


@st.cache_data(ttl=3600, show_spinner="한국은행 데이터를 불러오는 중…")
def load_series(ticker: str) -> pd.DataFrame:
    return data.load_series(ticker)


def fmt(value: float) -> str:
    """소수점 셋째 자리까지, 뒤쪽 0은 생략."""
    text = f"{value:,.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def build_figure(df: pd.DataFrame, colors: dict[str, str], separate: bool) -> go.Figure:
    columns = list(df.columns)
    rows = len(columns) if separate else 1
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06 if separate else 0,
        subplot_titles=columns if separate and rows > 1 else None,
    )
    for i, col in enumerate(columns):
        s = df[col].dropna()  # 관측 간격이 달라도 선이 끊기지 않게 지표별로 결측 제거
        # 기준금리처럼 변경일에만 값이 있는 드문 지표는 다음 변경까지 유지되므로 계단형으로 그린다
        sparse = len(s) < 0.2 * len(df)
        if sparse and len(s) and s.index[-1] < df.index[-1]:
            s = pd.concat([s, pd.Series([s.iloc[-1]], index=[df.index[-1]])])
        fig.add_trace(
            go.Scatter(
                x=s.index,
                y=s.values,
                name=col,
                mode="lines+markers" if len(s) < 40 else "lines",
                line=dict(color=colors[col], width=2, shape="hv" if sparse else "linear"),
                marker=dict(size=8, color=colors[col]),
                hovertemplate="%{y:,.3~f}<extra>" + col + "</extra>",
            ),
            row=(i + 1) if separate else 1,
            col=1,
        )
    fig.update_layout(
        height=max(420, 240 * rows) if separate else 480,
        hovermode="x unified",
        showlegend=len(columns) > 1 and not separate,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=8, r=8, t=48 if separate else 24, b=8),
    )
    fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1, spikedash="dot")
    fig.update_yaxes(tickformat=",~f", zeroline=False)
    return fig


st.title("한국은행 경제지표")

try:
    indicators = load_indicators()
except Exception as exc:
    st.error(f"지표 목록을 불러오지 못했습니다: {exc}")
    st.stop()

with st.sidebar:
    st.header("지표 선택")
    categories = list(dict.fromkeys(i.category for i in indicators))
    category = st.selectbox("분야", categories)
    choices = [i for i in indicators if i.category == category]
    indicator = st.radio("지표", choices, format_func=lambda i: i.name)
    st.caption(f"티커: `{indicator.ticker}`")

st.subheader(indicator.name)

try:
    raw = load_series(indicator.ticker)
except Exception as exc:
    st.error(f"한국은행 데이터를 불러오지 못했습니다: {exc}")
    st.stop()

if raw.empty:
    st.warning("데이터가 없습니다.")
    st.stop()

# 필터: 차트 바로 위 한 줄
c1, c2, c3, c4 = st.columns([3, 2, 2, 2], vertical_alignment="bottom")
period = c1.segmented_control("기간", list(PERIODS), default="10년")
frequency = c2.selectbox("주기", list(data.FREQUENCIES), help="월별·분기별·연별은 기간 내 마지막 관측값")
fill = c3.toggle("결측값 채우기", help="빈 날짜를 직전 관측값으로 채웁니다. 기준금리처럼 변경일에만 값이 있는 지표에 유용")
separate = c4.toggle("지표별 차트 분리", help="단위나 크기가 다른 지표를 각각의 축으로 비교")

all_columns = list(raw.columns)
selected = all_columns
if len(all_columns) > 1:
    selected = st.pills("표시할 지표", all_columns, selection_mode="multi", default=all_columns) or []
    if not selected:
        st.info("표시할 지표를 하나 이상 선택하세요.")
        st.stop()

years = PERIODS.get(period or "10년")
end = raw.index.max()
start = end - pd.DateOffset(years=years) if years else None
df = data.transform(raw[selected], start=start, fill=fill, frequency=frequency)

if df.empty:
    st.warning("선택한 기간에 데이터가 없습니다. 기간을 늘려 보세요.")
    st.stop()

# 최신값
theme = "dark" if st.context.theme.type == "dark" else "light"
colors = {col: PALETTE[theme][i % len(PALETTE[theme])] for i, col in enumerate(all_columns)}
latest = data.latest_values(df)
for col, item in zip(st.columns(max(len(latest), 1)), latest):
    col.metric(
        label=item.column,
        value=fmt(item.value),
        delta=None if item.change is None else fmt(item.change),
        delta_color="off",
        help=f"기준일 {item.date:%Y-%m-%d} · 변화는 직전 관측값 대비",
        border=True,
    )

st.plotly_chart(build_figure(df, colors, separate), use_container_width=True)
st.caption(
    f"{df.index.min():%Y-%m-%d} ~ {df.index.max():%Y-%m-%d} · {len(df):,}개 관측 · {SOURCE}"
)

with st.expander("데이터 표"):
    table = df.sort_index(ascending=False)
    table.index = table.index.strftime("%Y-%m-%d")
    st.dataframe(table, use_container_width=True)
    st.download_button(
        "CSV 다운로드",
        df.to_csv().encode("utf-8-sig"),  # 엑셀에서 한글이 깨지지 않게 BOM 포함
        file_name=f"{indicator.name}.csv",
        mime="text/csv",
    )
