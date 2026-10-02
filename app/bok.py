"""한국은행 금융경제 스냅샷(https://snapshot.bok.or.kr/) 데이터 조회."""

import threading
import time

import FinanceDataReader as fdr
import pandas as pd

SHORT_TERM_RATES_TICKER = "ECOS/SNAP/523"

# 스냅샷 원본 컬럼명 -> API 필드명
SHORT_TERM_RATE_COLUMNS = {
    "한국은행 기준금리": "base_rate",
    "콜금리(익일물)": "call_rate_overnight",
    "KORIBOR(3개월)": "koribor_3m",
    "CD수익률(91일)": "cd_91d",
}


class UpstreamError(Exception):
    """한국은행 스냅샷 데이터를 가져오지 못했을 때."""


class TTLCache:
    """티커별 DataFrame을 일정 시간 메모리에 보관한다.

    갱신에 실패하면 만료된 데이터라도 있으면 그것을 돌려준다.
    """

    def __init__(self, ttl_seconds: float = 3600):
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, pd.DataFrame]] = {}

    def get(self, ticker: str, loader) -> pd.DataFrame:
        with self._lock:
            entry = self._entries.get(ticker)
            if entry and time.monotonic() - entry[0] < self.ttl_seconds:
                return entry[1]
            try:
                df = loader(ticker)
            except Exception as exc:
                if entry:
                    return entry[1]
                raise UpstreamError(str(exc)) from exc
            self._entries[ticker] = (time.monotonic(), df)
            return df

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


cache = TTLCache()


def fetch_snapshot(ticker: str) -> pd.DataFrame:
    return fdr.SnapDataReader(ticker)


def get_short_term_rates() -> pd.DataFrame:
    """주요 단기 시장금리. 인덱스는 날짜, 컬럼은 SHORT_TERM_RATE_COLUMNS의 값."""
    df = cache.get(SHORT_TERM_RATES_TICKER, fetch_snapshot)
    missing = set(SHORT_TERM_RATE_COLUMNS) - set(df.columns)
    if missing:
        raise UpstreamError(f"예상한 컬럼이 없습니다: {sorted(missing)}")
    df = df[list(SHORT_TERM_RATE_COLUMNS)].rename(columns=SHORT_TERM_RATE_COLUMNS)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()
