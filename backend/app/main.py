from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import admin, companies, dashboard, jobs
from app.db import Base, engine

app = FastAPI(title="travel-salary-hub", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(companies.router)
app.include_router(jobs.router)
app.include_router(admin.router)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    from app.scheduler import start_scheduler
    start_scheduler()


dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """SPA 深链接回退：/companies 等前端路由返回 index.html。

        路径穿越防护：resolve 后必须仍在 dist 目录内（曾可 GET //data/salary.db 下载数据库）。
        """
        from fastapi.responses import FileResponse
        if full_path:
            candidate = (dist / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(dist.resolve()):
                return FileResponse(candidate)
        return FileResponse(dist / "index.html")
