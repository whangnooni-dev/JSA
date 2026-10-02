# JSA

이 프로젝트는 [uv](https://docs.astral.sh/uv/)로 관리합니다.

## 시작하기

```bash
# uv 설치 (미설치 시)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 의존성 설치 및 가상환경 생성 (.venv)
uv sync

# 개발 서버 실행 (자동 리로드) — http://127.0.0.1:8000, API 문서: /docs
uv run fastapi dev main.py

# 프로덕션 실행
uv run fastapi run main.py
```

## 자주 쓰는 명령

```bash
uv add <패키지>          # 의존성 추가
uv add --dev <패키지>    # 개발용 의존성 추가
uv remove <패키지>       # 의존성 제거
uv lock --upgrade        # 의존성 업그레이드
```
