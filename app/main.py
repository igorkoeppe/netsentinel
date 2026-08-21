from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description="Network monitoring and security observability platform.",
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.APP_NAME.lower()}
