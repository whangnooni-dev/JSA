"""한국은행 금융경제 스냅샷 데이터 조회와 가공 (Streamlit 의존 없음)."""

from dataclasses import dataclass

import FinanceDataReader as fdr
import pandas as pd

# 분야 -> 티커 (FinanceDataReader의 ECOS/SNAP/LIST 순서를 따름)
CATEGORIES: dict[str, list[str]] = {
    "금리": ["523", "512", "861"],
    "가계부채": ["517-1", "517-2"],
    "통화·유동성": ["527", "528"],
    "환율": ["529", "530"],
    "증시·채권": ["531", "532", "533"],
    "성장·국민계정": ["1184", "1191", "1193-1", "1193-2", "1195-1", "1195-2", "1195-3"],
    "생산·투자": ["1196", "1198", "1200", "1202", "1203", "1205", "1206"],
    "경기·심리": ["1207", "1208", "1209"],
    "가계·분배": ["1210", "1211"],
    "고용·인구": ["1212", "1213", "1214", "1204", "1201"],
    "대외": ["1199", "1194", "1192", "1190", "1188-1", "1188-2", "1188-3"],
    "물가·자산": ["1197", "1187", "1186", "1511"],
}

# FinanceDataReader 목록에서 '교역조건지수'는 티커가 1198(제조업 출하·재고·가동률)로
# 잘못 연결되어 있어 제외한다.
EXCLUDED_DESCRIPTIONS = {"교역조건지수"}


@dataclass(frozen=True)
class Indicator:
    ticker: str
    name: str
    category: str


def ticker_of(code: str) -> str:
    return f"ECOS/SNAP/{code}"


def load_indicators() -> list[Indicator]:
    """분야 순서대로 정렬한 지표 목록."""
    listing = fdr.SnapDataReader("ECOS/SNAP/LIST")
    listing = listing[~listing["Desc"].isin(EXCLUDED_DESCRIPTIONS)]
    names = dict(zip(listing["Ticker"], listing["Desc"]))

    indicators = []
    for category, codes in CATEGORIES.items():
        for code in codes:
            ticker = ticker_of(code)
            if ticker in names:
                indicators.append(Indicator(ticker, names[ticker], category))
    # 목록에 새로 생긴 티커도 빠뜨리지 않는다
    known = {i.ticker for i in indicators}
    for ticker, name in names.items():
        if ticker not in known:
            indicators.append(Indicator(ticker, name, "기타"))
    return indicators


def load_series(ticker: str) -> pd.DataFrame:
    """날짜 인덱스, 지표별 컬럼의 숫자형 DataFrame."""
    df = fdr.SnapDataReader(ticker)
    df.index = pd.to_datetime(df.index)
    df = df.apply(pd.to_numeric, errors="coerce")
    return df.sort_index().dropna(how="all")


FREQUENCIES = {"원자료": None, "월별": "ME", "분기별": "QE", "연별": "YE"}


def transform(
    df: pd.DataFrame,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    fill: bool = False,
    frequency: str = "원자료",
) -> pd.DataFrame:
    """결측 채우기 -> 주기 변환(기간별 마지막 관측값) -> 기간 필터.

    채우기를 먼저 해서 조회 시작일 이전의 마지막 값이 기간 안으로 이어지게 한다.
    """
    if fill:
        df = df.ffill()
    rule = FREQUENCIES[frequency]
    if rule:
        df = df.resample(rule).last()
    if start is not None:
        df = df[df.index >= start]
    if end is not None:
        df = df[df.index <= end]
    return df.dropna(how="all")


@dataclass(frozen=True)
class Latest:
    column: str
    date: pd.Timestamp
    value: float
    change: float | None  # 직전 관측값 대비


def latest_values(df: pd.DataFrame) -> list[Latest]:
    """컬럼별 최신값과 직전 관측값 대비 변화. 값이 없는 컬럼은 건너뛴다."""
    result = []
    for col in df.columns:
        s = df[col].dropna()
        if s.empty:
            continue
        change = float(s.iloc[-1] - s.iloc[-2]) if len(s) > 1 else None
        result.append(Latest(col, s.index[-1], float(s.iloc[-1]), change))
    return result
