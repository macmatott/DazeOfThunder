"""
Formula Fantasy website — FastAPI + Jinja2 + HTMX, no build step, no JS
framework. Run with: uvicorn app.main:app --reload (from frontend/).
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import pages, partials

app = FastAPI(title="Daze of Thunder — Formula Fantasy")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(pages.router)
app.include_router(partials.router)
