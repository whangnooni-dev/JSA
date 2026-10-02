"""한국은행 금융경제 스냅샷 데이터 조회와 가공 (Streamlit 의존 없음)."""

import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import FinanceDataReader as fdr
import pandas as pd

# 한국은행에서 받은 데이터를 저장해 두는 곳. 접속이 안 될 때 여기서 읽는다.
SNAPSHOT_DIR = Path(os.environ.get("JSA_SNAPSHOT_DIR", Path(__file__).resolve().parent.parent / "data" / "snapshots"))
# true면 한국은행에 접속하지 않고 저장본만 사용
OFFLINE = os.environ.get("JSA_OFFLINE", "").lower() in ("1", "true", "yes")
# FinanceDataReader는 요청 타임아웃이 없어 서버가 응답하지 않으면 무한정 기다린다
FETCH_TIMEOUT_SECONDS = float(os.environ.get("JSA_FETCH_TIMEOUT", "20"))

_executor = ThreadPoolExecutor(max_workers=4)

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


class DataUnavailable(Exception):
    """한국은행 접속도 실패했고 저장본도 없을 때."""


@dataclass(frozen=True)
class SeriesResult:
    data: pd.DataFrame
    source: str  # "live": 한국은행에서 방금 받음, "snapshot": 저장본
    saved_at: datetime
    error: str | None = None  # 저장본을 쓴 경우 실시간 조회 실패 사유


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df.index.name = "날짜"
    df = df.apply(pd.to_numeric, errors="coerce")
    return df.sort_index().dropna(how="all")


def snapshot_path(ticker: str) -> Path:
    return SNAPSHOT_DIR / f"{ticker.replace('ECOS/SNAP/', '')}.csv"


# 저장본 첫 줄에 받은 시각을 기록한다 (파일 수정 시각은 git clone 등으로 바뀌므로 쓰지 않음)
_SAVED_AT_PREFIX = "# saved_at="


def save_snapshot(ticker: str, df: pd.DataFrame, saved_at: datetime | None = None) -> Path:
    path = snapshot_path(ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(f"{_SAVED_AT_PREFIX}{(saved_at or datetime.now()).isoformat(timespec='seconds')}\n")
        df.to_csv(f)
    tmp.replace(path)  # 쓰는 도중 실패해도 기존 저장본이 깨지지 않게
    return path


def read_snapshot(ticker: str) -> tuple[pd.DataFrame, datetime] | None:
    path = snapshot_path(ticker)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        first = f.readline()
        if first.startswith(_SAVED_AT_PREFIX):
            saved_at = datetime.fromisoformat(first[len(_SAVED_AT_PREFIX):].strip())
        else:
            f.seek(0)
            saved_at = datetime.fromtimestamp(path.stat().st_mtime)
        df = pd.read_csv(f, index_col=0)
    return _normalize(df), saved_at


def fetch_live(ticker: str, timeout: float = FETCH_TIMEOUT_SECONDS) -> pd.DataFrame:
    future = _executor.submit(fdr.SnapDataReader, ticker)
    try:
        df = future.result(timeout=timeout)
    except FutureTimeout:
        raise TimeoutError(f"{timeout:g}초 안에 응답이 없습니다") from None
    df = _normalize(df)
    if df.empty:
        raise ValueError("받은 데이터가 비어 있습니다")
    return df


def load_series(ticker: str) -> SeriesResult:
    """한국은행에서 받아 저장본을 갱신하고, 실패하면 저장본을 돌려준다."""
    error = "오프라인 모드 (JSA_OFFLINE)"
    if not OFFLINE:
        try:
            df = fetch_live(ticker)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        else:
            try:
                save_snapshot(ticker, df)
            except OSError:
                pass  # 저장 실패는 화면 표시에 영향 없음
            return SeriesResult(df, "live", datetime.now())

    snapshot = read_snapshot(ticker)
    if snapshot is None:
        raise DataUnavailable(f"한국은행 데이터를 받지 못했고 저장본도 없습니다 ({error})")
    df, saved_at = snapshot
    return SeriesResult(df, "snapshot", saved_at, error)


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
