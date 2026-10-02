# JSA

한국은행 금융경제 스냅샷(https://snapshot.bok.or.kr/) 데이터를 보여 주는 Streamlit 대시보드와 FastAPI 서버입니다.
데이터 수집은 [FinanceDataReader](https://github.com/FinanceData/FinanceDataReader)의 `SnapDataReader`를 사용합니다.
프로젝트는 [uv](https://docs.astral.sh/uv/)로 관리합니다.

## 시작하기

```bash
# uv 설치 (미설치 시)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 의존성 설치 및 가상환경 생성 (.venv)
uv sync

# 개발 서버 실행 (자동 리로드) — http://127.0.0.1:8000, API 문서: /docs
uv run fastapi dev

# 프로덕션 실행
uv run fastapi run

# 테스트
uv run pytest
```

진입점은 `pyproject.toml`의 `[tool.fastapi] entrypoint = "app.main:app"`로 지정되어 있습니다.

## 대시보드 (Streamlit)

```bash
uv run streamlit run dashboard/app.py
```

브라우저에서 http://localhost:8501 이 열립니다.

- 왼쪽 사이드바에서 분야와 지표를 선택합니다. 스냅샷 지표 47개를 12개 분야로 묶었습니다.
- 차트 위에서 기간(1·3·5·10년·전체), 주기(원자료·월별·분기별·연별), 결측값 채우기, 지표별 차트 분리를 고릅니다.
- 지표별 최신값과 직전 관측값 대비 변화를 카드로 보여 줍니다.
- Plotly 차트에서 마우스를 올리면 날짜별 값을 보여 줍니다. 아래 데이터 표에서 CSV로 내려받을 수 있습니다.
- 데이터는 1시간 동안 캐시합니다.
- FinanceDataReader 목록의 `교역조건지수`는 티커가 제조업 지표(1198)로 잘못 연결되어 있어 제외했습니다.

코드: `dashboard/data.py`(데이터 조회·가공), `dashboard/app.py`(화면)

## API (보류)

### `GET /api/v1/rates/short-term` — 주요 단기 시장금리

원천: 한국은행 스냅샷 `ECOS/SNAP/523`, 단위 연%.

| 필드 | 지표 |
|---|---|
| `base_rate` | 한국은행 기준금리 |
| `call_rate_overnight` | 콜금리(익일물) |
| `koribor_3m` | KORIBOR(3개월) |
| `cd_91d` | CD수익률(91일) |

| 쿼리 파라미터 | 기본값 | 설명 |
|---|---|---|
| `start`, `end` | 없음 | 조회 기간 (YYYY-MM-DD, 양 끝 포함) |
| `frequency` | `daily` | `daily`: 원자료, `monthly`: 월별 마지막 관측값 (날짜는 월말) |
| `fill` | `false` | `true`면 결측값을 직전 관측값으로 채움 |

지표마다 시작 시점과 발표 주기가 달라 원자료에는 `null`이 많습니다.
특히 기준금리는 일부 날짜에만 값이 있으므로 날짜별 비교에는 `fill=true`를 권장합니다.

```bash
curl 'http://127.0.0.1:8000/api/v1/rates/short-term?start=2025-01-01&frequency=monthly&fill=true'
```

```json
{
  "source": "한국은행 금융경제 스냅샷 (ECOS/SNAP/523)",
  "unit": "연%",
  "frequency": "monthly",
  "series": [{"field": "base_rate", "name": "한국은행 기준금리"}, "..."],
  "count": 6,
  "data": [
    {"date": "2025-06-30", "base_rate": 2.5, "call_rate_overnight": 2.458, "koribor_3m": 2.57, "cd_91d": 2.56}
  ]
}
```

### `GET /api/v1/rates/short-term/latest` — 지표별 최신값

```json
{
  "source": "한국은행 금융경제 스냅샷 (ECOS/SNAP/523)",
  "unit": "연%",
  "base_rate": {"date": "2025-06-09", "value": 2.5},
  "call_rate_overnight": {"date": "2025-06-11", "value": 2.484},
  "koribor_3m": {"date": "2025-06-12", "value": 2.57},
  "cd_91d": {"date": "2025-06-11", "value": 2.57}
}
```

### 캐싱과 오류

- 한국은행 데이터는 프로세스 메모리에 1시간 캐시합니다.
- 갱신에 실패하면 이전에 받아 둔 데이터를 그대로 응답합니다.
- 받아 둔 데이터도 없으면 `502`를 응답합니다.

## 자주 쓰는 명령

```bash
uv add <패키지>          # 의존성 추가
uv add --dev <패키지>    # 개발용 의존성 추가
uv remove <패키지>       # 의존성 제거
uv lock --upgrade        # 의존성 업그레이드
```
