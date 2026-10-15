from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import health, market, okk, portfolio, proposal
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.service_name,
    version="0.1.0",
    description="Local read-only gateway for OKX Agent Trade Kit and OKK AI trading workflows.",
)

app.include_router(health.router)
app.include_router(market.router, prefix="/market", tags=["market"])
app.include_router(portfolio.router, prefix="/portfolio", tags=["portfolio"])
app.include_router(proposal.router, prefix="/proposal", tags=["proposal"])
app.include_router(okk.router, prefix="/okk", tags=["okk-bridge"])

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/ui", StaticFiles(directory=static_dir, html=True), name="ui")


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")
