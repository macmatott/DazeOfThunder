"""
Formula Fantasy website — FastAPI + Jinja2 + HTMX, no build step, no JS
framework. Run with: uvicorn app.main:app --reload (from frontend/).
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.middleware import CurrentUserMiddleware
from app.routers import auth, pages, partials

app = FastAPI(title="Daze of Thunder — Formula Fantasy")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Starlette's add_middleware() inserts at the front of the stack, so the
# middleware added *last* runs *first* on each request. CurrentUserMiddleware
# reads request.session, so SessionMiddleware must be added after it (i.e.
# run before it).
app.add_middleware(CurrentUserMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="ff_session",
    same_site="lax",
    https_only=settings.environment == "production",
)

app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(partials.router)
