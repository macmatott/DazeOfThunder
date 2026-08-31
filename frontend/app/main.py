"""
Formula Fantasy website — FastAPI + Jinja2 + HTMX, no build step, no JS
framework. Run with: uvicorn app.main:app --reload (from frontend/).
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.middleware import CurrentUserMiddleware
from app.routers import admin, auth, draft, internal, pages, partials, team_events

app = FastAPI(title="Daze of Thunder — Formula Fantasy")

app.mount("/static", StaticFiles(directory="app/static"), name="static")


# StaticFiles sends Last-Modified/ETag but no Cache-Control, so browsers
# fall back to heuristic caching (RFC 7234 §4.2.2) and can silently keep
# serving a stale JS/CSS file after a deploy with no visible sign
# anything's wrong — this bit us directly debugging the standings chart
# fixes, where a hard refresh was needed to see a change take effect.
# no-cache (not no-store) still lets the browser cache the file — it
# just forces a conditional GET (If-None-Match) on every load, which is
# cheap and returns 304 unless the file actually changed.
@app.middleware("http")
async def no_cache_for_static(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

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

app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(draft.router)
app.include_router(internal.router)
app.include_router(pages.router)
app.include_router(partials.router)
app.include_router(team_events.router)
