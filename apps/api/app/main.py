from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

# Local-development CORS only: the Vite dev server (apps/web) runs on a different
# origin than the API, so the browser blocks its fetches without this. No credentials
# (cookies/Authorization) are used anywhere in this app, so allow_credentials stays at
# its default (False) -- only GET requests are needed, since this is a read-only API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router, prefix=settings.api_v1_prefix)
