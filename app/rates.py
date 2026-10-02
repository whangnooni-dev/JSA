from datetime import date
from enum import Enum

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import bok

router = APIRouter(prefix="/api/v1/rates", tags=["rates"])


class Frequency(str, Enum):
    daily = "daily"
    monthly = "monthly"


class SeriesInfo(BaseModel):
    field: str
    name: str = Field(description="한국은행 스냅샷 원본 지표명")


class ShortTermRate(BaseModel):
    date: date
    base_rate: float | None = Field(None, description="한국은행 기준금리 (연%)")
    call_rate_overnight: float | None = Field(None, description="콜금리(익일물) (연%)")
    koribor_3m: float | None = Field(None, description="KORIBOR(3개월) (연%)")
    cd_91d: float | None = Field(None, description="CD수익률(91일) (연%)")


class ShortTermRatesResponse(BaseModel):
    source: str = "한국은행 금융경제 스냅샷 (ECOS/SNAP/523)"
    unit: str = "연%"
    frequency: Frequency
    series: list[SeriesInfo]
    count: int
    data: list[ShortTermRate]


class LatestValue(BaseModel):
    date: date
    value: float


class LatestShortTermRatesResponse(BaseModel):
    source: str = "한국은행 금융경제 스냅샷 (ECOS/SNAP/523)"
    unit: str = "연%"
    base_rate: LatestValue | None
    call_rate_overnight: LatestValue | None
    koribor_3m: LatestValue | None
    cd_91d: LatestValue | None


SERIES = [SeriesInfo(field=f, name=n) for n, f in bok.SHORT_TERM_RATE_COLUMNS.items()]


def _load() -> pd.DataFrame:
    try:
        return bok.get_short_term_rates()
    except bok.UpstreamError as exc:
        raise HTTPException(status_code=502, detail=f"한국은행 데이터 조회 실패: {exc}")


@router.get("/short-term", response_model=ShortTermRatesResponse)
def short_term_rates(
    start: date | None = Query(None, description="시작일 (YYYY-MM-DD, 포함)"),
    end: date | None = Query(None, description="종료일 (YYYY-MM-DD, 포함)"),
    frequency: Frequency = Query(
        Frequency.daily, description="daily: 원자료, monthly: 월별 마지막 관측값 (날짜는 월말)"
    ),
    fill: bool = Query(
        False, description="true면 결측값을 직전 관측값으로 채움 (기준금리 등 비연속 지표용)"
    ),
):
    """주요 단기 시장금리: 기준금리, 콜금리(익일물), KORIBOR(3개월), CD수익률(91일)."""
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="start는 end보다 이후일 수 없습니다.")

    df = _load()
    if fill:
        df = df.ffill()
    if frequency is Frequency.monthly:
        df = df.resample("ME").last()
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    df = df.dropna(how="all")

    data = [
        ShortTermRate(
            date=ts.date(), **{k: (None if pd.isna(v) else float(v)) for k, v in row.items()}
        )
        for ts, row in df.iterrows()
    ]
    return ShortTermRatesResponse(frequency=frequency, series=SERIES, count=len(data), data=data)


@router.get("/short-term/latest", response_model=LatestShortTermRatesResponse)
def latest_short_term_rates():
    """지표별 가장 최근 관측값과 그 날짜."""
    df = _load()
    latest = {}
    for field in bok.SHORT_TERM_RATE_COLUMNS.values():
        s = df[field].dropna()
        latest[field] = (
            LatestValue(date=s.index[-1].date(), value=float(s.iloc[-1])) if len(s) else None
        )
    return LatestShortTermRatesResponse(**latest)
