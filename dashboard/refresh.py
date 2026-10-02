"""모든 스냅샷 지표를 한국은행에서 받아 data/snapshots/에 저장한다.

실행: uv run python -m dashboard.refresh
한국은행 사이트에 접속되는 PC에서 실행한 뒤 저장본을 커밋하면,
접속이 막힌 환경에서도 대시보드가 저장본으로 동작한다.
"""

import sys

from dashboard import data


def main() -> int:
    indicators = data.load_indicators()
    failed = []
    for i, indicator in enumerate(indicators, 1):
        label = f"[{i:2}/{len(indicators)}] {indicator.ticker:<18} {indicator.name}"
        try:
            df = data.fetch_live(indicator.ticker)
            path = data.save_snapshot(indicator.ticker, df)
        except Exception as exc:
            failed.append(indicator)
            print(f"{label}  실패: {type(exc).__name__}: {exc}")
        else:
            print(f"{label}  {len(df):,}행 ~ {df.index.max():%Y-%m-%d} -> {path.name}")

    print(f"\n완료: {len(indicators) - len(failed)}개 저장, {len(failed)}개 실패 ({data.SNAPSHOT_DIR})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
