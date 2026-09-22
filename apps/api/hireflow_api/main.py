from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hireflow_api.config import settings
from hireflow_api.db import init_db
from hireflow_api.queue import close_queue, init_queue
from hireflow_api.routes.auth import router as auth_router
from hireflow_api.routes.candidates import router as candidates_router
from hireflow_api.routes.files import router as files_router
from hireflow_api.routes.gaps import router as gaps_router
from hireflow_api.routes.jobs import router as jobs_router
from hireflow_api.routes.plans import router as plans_router
from hireflow_api.routes.reports import router as reports_router
from hireflow_api.routes.requirements import router as requirements_router
from hireflow_api.routes.runs import router as runs_router
from hireflow_api.routes.transcripts import router as transcripts_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    await init_queue()
    yield
    await close_queue()


app = FastAPI(title="HireFlow API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(candidates_router)
app.include_router(plans_router)
app.include_router(transcripts_router)
app.include_router(reports_router)
app.include_router(runs_router)
app.include_router(requirements_router)
app.include_router(gaps_router)
app.include_router(files_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "store": "supabase"}
