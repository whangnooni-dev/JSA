from fastapi import FastAPI

from app import rates

app = FastAPI(
    title="JSA",
    description="한국은행 금융경제 스냅샷 데이터 API",
)
app.include_router(rates.router)


@app.get("/health")
def health():
    return {"status": "ok"}
