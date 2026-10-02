import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import bok
from app.main import app

NaN = np.nan


def sample_snapshot() -> pd.DataFrame:
    """fdr.SnapDataReader('ECOS/SNAP/523')와 같은 모양의 데이터."""
    df = pd.DataFrame(
        {
            "한국은행 기준금리": [NaN, 2.75, NaN, 2.5, 2.5, NaN, NaN],
            "콜금리(익일물)": [NaN, 2.80, 2.70, NaN, 2.523, 2.458, NaN],
            "KORIBOR(3개월)": [NaN, NaN, 2.75, NaN, 2.58, 2.58, 2.57],
            "CD수익률(91일)": [14.70, NaN, 2.74, NaN, 2.57, 2.56, NaN],
        },
        index=pd.to_datetime(
            [
                "1995-01-03",
                "2025-04-30",
                "2025-05-02",
                "2025-06-08",
                "2025-06-09",
                "2025-06-10",
                "2025-06-12",
            ]
        ),
    )
    df.index.name = "날짜"
    return df


@pytest.fixture
def client(monkeypatch):
    bok.cache.clear()
    calls = []

    def fake_fetch(ticker):
        calls.append(ticker)
        return sample_snapshot()

    monkeypatch.setattr(bok, "fetch_snapshot", fake_fetch)
    with TestClient(app) as c:
        c.calls = calls
        yield c
    bok.cache.clear()


def test_short_term_rates_daily(client):
    res = client.get("/api/v1/rates/short-term")
    assert res.status_code == 200
    body = res.json()
    assert body["frequency"] == "daily"
    assert body["count"] == 7
    assert [s["field"] for s in body["series"]] == [
        "base_rate",
        "call_rate_overnight",
        "koribor_3m",
        "cd_91d",
    ]
    assert body["data"][0] == {
        "date": "1995-01-03",
        "base_rate": None,
        "call_rate_overnight": None,
        "koribor_3m": None,
        "cd_91d": 14.7,
    }
    assert body["data"][4]["call_rate_overnight"] == 2.523


def test_short_term_rates_date_range(client):
    res = client.get("/api/v1/rates/short-term", params={"start": "2025-06-09", "end": "2025-06-10"})
    assert [d["date"] for d in res.json()["data"]] == ["2025-06-09", "2025-06-10"]


def test_short_term_rates_fill_carries_values_into_range(client):
    res = client.get("/api/v1/rates/short-term", params={"start": "2025-06-12", "fill": True})
    (row,) = res.json()["data"]
    assert row == {
        "date": "2025-06-12",
        "base_rate": 2.5,
        "call_rate_overnight": 2.458,
        "koribor_3m": 2.57,
        "cd_91d": 2.56,
    }


def test_short_term_rates_monthly(client):
    res = client.get(
        "/api/v1/rates/short-term", params={"start": "2025-01-01", "frequency": "monthly"}
    )
    data = res.json()["data"]
    assert [d["date"] for d in data] == ["2025-04-30", "2025-05-31", "2025-06-30"]
    assert data[2] == {
        "date": "2025-06-30",
        "base_rate": 2.5,
        "call_rate_overnight": 2.458,
        "koribor_3m": 2.57,
        "cd_91d": 2.56,
    }


def test_short_term_rates_rejects_inverted_range(client):
    res = client.get("/api/v1/rates/short-term", params={"start": "2025-06-10", "end": "2025-06-01"})
    assert res.status_code == 422


def test_latest(client):
    res = client.get("/api/v1/rates/short-term/latest")
    assert res.status_code == 200
    body = res.json()
    assert body["base_rate"] == {"date": "2025-06-09", "value": 2.5}
    assert body["call_rate_overnight"] == {"date": "2025-06-10", "value": 2.458}
    assert body["koribor_3m"] == {"date": "2025-06-12", "value": 2.57}
    assert body["cd_91d"] == {"date": "2025-06-10", "value": 2.56}


def test_snapshot_is_cached(client):
    client.get("/api/v1/rates/short-term")
    client.get("/api/v1/rates/short-term/latest")
    assert client.calls == [bok.SHORT_TERM_RATES_TICKER]


def test_upstream_failure_returns_502(monkeypatch):
    bok.cache.clear()

    def failing_fetch(ticker):
        raise ConnectionError("blocked")

    monkeypatch.setattr(bok, "fetch_snapshot", failing_fetch)
    res = TestClient(app).get("/api/v1/rates/short-term")
    assert res.status_code == 502


def test_stale_data_served_when_refresh_fails(monkeypatch):
    cache = bok.TTLCache(ttl_seconds=0)
    assert cache.get("X", lambda t: sample_snapshot()).shape == (7, 4)
    stale = cache.get("X", lambda t: (_ for _ in ()).throw(ConnectionError()))
    assert stale.shape == (7, 4)


def test_fetch_snapshot_parses_bok_excel_export(monkeypatch):
    """FinanceDataReader의 실제 엑셀 파싱 경로를 거친다 (openpyxl 의존성 확인용)."""
    import io

    import requests
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["주요 단기 시장금리"])
    ws.append([])
    ws.append([])
    ws.append(["", *bok.SHORT_TERM_RATE_COLUMNS])
    ws.append(["단위", "연%", "연%", "연%", "연%"])
    ws.append(["주기", "일", "일", "일", "일"])
    ws.append(["기간", "", "", "", ""])
    ws.append(["2025-06-09", 2.5, 2.523, 2.58, 2.57])
    ws.append(["2025-06-10", None, 2.458, 2.58, 2.56])
    buf = io.BytesIO()
    wb.save(buf)

    class FakeResponse:
        content = buf.getvalue()

    monkeypatch.setattr(requests, "get", lambda url, *a, **kw: FakeResponse())
    df = bok.fetch_snapshot(bok.SHORT_TERM_RATES_TICKER)
    assert list(df.columns) == list(bok.SHORT_TERM_RATE_COLUMNS)
    assert df.loc["2025-06-10", "콜금리(익일물)"] == 2.458
