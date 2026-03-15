from fastapi import FastAPI

app = FastAPI(title="Mockups MPC")

@app.get("/health")
async def health():
    return {"status": "ok"}
