import numpy as np
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard import data

NaN = np.nan

LISTING = pd.DataFrame(
    {
        "Ticker": ["ECOS/SNAP/523", "ECOS/SNAP/517-1", "ECOS/SNAP/1198", "ECOS/SNAP/1198", "ECOS/SNAP/9999"],
        "Desc": ["주요 단기 시장금리", "가계신용", "제조업 출하, 재고, 가동률지수", "교역조건지수", "신규 지표"],
        "Columns": ["", "", "", "", ""],
    }
)


def rates() -> pd.DataFrame:
    idx = pd.date_range("2015-01-01", "2025-06-30", freq="D")
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "한국은행 기준금리": NaN,
            "콜금리(익일물)": 2 + rng.normal(0, 0.1, len(idx)).cumsum() / 30,
            "KORIBOR(3개월)": 2.2 + rng.normal(0, 0.1, len(idx)).cumsum() / 30,
            "CD수익률(91일)": 2.3 + rng.normal(0, 0.1, len(idx)).cumsum() / 30,
        },
        index=idx,
    )
    df.loc["2024-10-11", "한국은행 기준금리"] = 3.25
    df.loc["2025-05-29", "한국은행 기준금리"] = 2.5
    df.index.name = "날짜"
    return df


def household_credit() -> pd.DataFrame:
    # 서브코드(517-1) 경로는 float 변환 없이 object로 내려온다
    df = pd.DataFrame(
        {"가계신용": ["1800.5", "1850.1", "1862.0"]},
        index=pd.to_datetime(["2024-09-01", "2024-12-01", "2025-03-01"]),
    )
    df.index.name = "날짜"
    return df


def fake_reader(ticker):
    return {
        "ECOS/SNAP/LIST": LISTING,
        "ECOS/SNAP/523": rates(),
        "ECOS/SNAP/517-1": household_credit(),
    }[ticker].copy()


@pytest.fixture(autouse=True)
def fake_fdr(monkeypatch, tmp_path):
    st.cache_data.clear()
    monkeypatch.setattr(data.fdr, "SnapDataReader", fake_reader)
    monkeypatch.setattr(data, "SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(data, "OFFLINE", False)
    yield
    st.cache_data.clear()


def test_load_indicators_orders_by_category_and_drops_bad_entry():
    indicators = data.load_indicators()
    assert [(i.ticker, i.category) for i in indicators] == [
        ("ECOS/SNAP/523", "금리"),
        ("ECOS/SNAP/517-1", "가계부채"),
        ("ECOS/SNAP/1198", "생산·투자"),
        ("ECOS/SNAP/9999", "기타"),
    ]
    assert all(i.name != "교역조건지수" for i in indicators)


def test_load_series_coerces_numeric():
    result = data.load_series("ECOS/SNAP/517-1")
    assert result.source == "live"
    assert result.data["가계신용"].dtype == float
    assert result.data["가계신용"].iloc[-1] == 1862.0


def blocked(ticker):
    if ticker == "ECOS/SNAP/LIST":
        return LISTING.copy()  # 목록은 라이브러리에 내장되어 네트워크가 필요 없다
    raise ConnectionError("Tunnel connection failed: 403 Forbidden")


def test_live_fetch_saves_snapshot_used_when_blocked(monkeypatch):
    live = data.load_series("ECOS/SNAP/523")
    assert data.snapshot_path("ECOS/SNAP/523").exists()

    monkeypatch.setattr(data.fdr, "SnapDataReader", blocked)
    result = data.load_series("ECOS/SNAP/523")
    assert result.source == "snapshot"
    assert "403 Forbidden" in result.error
    assert abs((result.saved_at - live.saved_at).total_seconds()) < 5
    pd.testing.assert_frame_equal(result.data, live.data, check_freq=False)


def test_snapshot_keeps_saved_at_independent_of_file_mtime():
    from datetime import datetime

    data.save_snapshot("ECOS/SNAP/523", rates(), saved_at=datetime(2025, 6, 13, 9, 30))
    _, saved_at = data.read_snapshot("ECOS/SNAP/523")
    assert saved_at == datetime(2025, 6, 13, 9, 30)


def test_no_live_and_no_snapshot_raises(monkeypatch):
    monkeypatch.setattr(data.fdr, "SnapDataReader", blocked)
    with pytest.raises(data.DataUnavailable, match="403"):
        data.load_series("ECOS/SNAP/523")


def test_offline_mode_skips_network(monkeypatch):
    data.save_snapshot("ECOS/SNAP/523", rates())
    calls = []
    monkeypatch.setattr(data.fdr, "SnapDataReader", lambda t: calls.append(t))
    monkeypatch.setattr(data, "OFFLINE", True)
    assert data.load_series("ECOS/SNAP/523").source == "snapshot"
    assert calls == []


def test_fetch_times_out(monkeypatch):
    import threading

    release = threading.Event()
    monkeypatch.setattr(data.fdr, "SnapDataReader", lambda t: release.wait(5))
    try:
        with pytest.raises(TimeoutError):
            data.fetch_live("ECOS/SNAP/523", timeout=0.2)
    finally:
        release.set()


def test_transform_fill_carries_value_into_range():
    df = data.transform(rates(), start=pd.Timestamp("2025-06-01"), fill=True)
    assert (df["한국은행 기준금리"] == 2.5).all()
    df = data.transform(rates(), start=pd.Timestamp("2025-06-01"))
    assert df["한국은행 기준금리"].isna().all()


def test_transform_monthly_uses_last_observation():
    df = data.transform(rates(), frequency="월별", start=pd.Timestamp("2025-05-01"))
    assert list(df.index.strftime("%Y-%m-%d")) == ["2025-05-31", "2025-06-30"]
    assert df.loc["2025-05-31", "한국은행 기준금리"] == 2.5
    assert np.isnan(df.loc["2025-06-30", "한국은행 기준금리"])


def test_latest_values():
    latest = {item.column: item for item in data.latest_values(rates())}
    base = latest["한국은행 기준금리"]
    assert (base.date, base.value, base.change) == (pd.Timestamp("2025-05-29"), 2.5, -0.75)


def run_app() -> AppTest:
    at = AppTest.from_file("../dashboard/app.py", default_timeout=30)
    return at.run()


def test_app_renders_default_indicator():
    at = run_app()
    assert not at.exception
    assert not at.error
    assert at.subheader[0].value == "주요 단기 시장금리"
    assert [m.label for m in at.metric] == [
        "한국은행 기준금리",
        "콜금리(익일물)",
        "KORIBOR(3개월)",
        "CD수익률(91일)",
    ]
    assert at.metric[0].value == "2.5"


def test_app_switches_indicator_and_options():
    at = run_app()
    at.sidebar.selectbox[0].select("가계부채").run()
    assert not at.exception
    assert at.subheader[0].value == "가계신용"
    assert at.metric[0].value == "1,862"

    at.sidebar.selectbox[0].select("금리").run()
    at.toggle[0].set_value(True).run()  # 결측 채우기
    at.toggle[1].set_value(True).run()  # 차트 분리
    assert not at.exception


def test_app_uses_snapshot_with_warning_when_blocked(monkeypatch):
    data.save_snapshot("ECOS/SNAP/523", rates())
    monkeypatch.setattr(data.fdr, "SnapDataReader", blocked)
    at = run_app()
    assert not at.exception
    assert "저장본" in at.warning[0].value
    assert at.metric[0].value == "2.5"


def test_app_explains_how_to_get_data_when_nothing_available(monkeypatch):
    monkeypatch.setattr(data.fdr, "SnapDataReader", blocked)
    at = run_app()
    assert not at.exception
    assert "저장본도 없습니다" in at.error[0].value
    assert "dashboard.refresh" in at.info[0].value


def test_refresh_saves_all_and_reports_failures(monkeypatch, capsys):
    from dashboard import refresh

    assert refresh.main() == 1  # 가짜 목록의 1198, 9999는 데이터가 없어 실패
    assert data.snapshot_path("ECOS/SNAP/523").exists()
    assert data.snapshot_path("ECOS/SNAP/517-1").exists()
    out = capsys.readouterr().out
    assert "2개 저장, 2개 실패" in out
