from fastapi import FastAPI

app = FastAPI(title="JSA")


@app.get("/")
def read_root():
    return {"message": "Hello from jsa!"}


@app.get("/health")
def health():
    return {"status": "ok"}
