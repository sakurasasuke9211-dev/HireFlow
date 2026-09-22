from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from hireflow_api.auth import get_current_user
from hireflow_api.config import settings
from hireflow_api.models import User
from hireflow_api.services import (
    UploadError,
    create_job,
    get_job_detail,
    get_matrix,
    list_jobs,
    list_requirements,
    start_parse,
    store_and_extract,
)
from hireflow_domain.enums import DocumentKind, DocumentOwnerType
from hireflow_domain.schemas import (
    JobCreate,
    JobDetail,
    JobSummary,
    MatrixResponse,
    PipelineRunPublic,
    RequirementPublic,
    UploadResult,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobSummary])
async def get_jobs(user: User = Depends(get_current_user)) -> list[JobSummary]:
    return await list_jobs(user.org_id)


@router.post("", response_model=JobDetail, status_code=status.HTTP_201_CREATED)
async def create_job_route(body: JobCreate, user: User = Depends(get_current_user)) -> JobDetail:
    job = await create_job(org_id=user.org_id, user_id=user.id, title=body.title)
    detail = await get_job_detail(org_id=user.org_id, job_id=job.id)
    assert detail is not None
    return detail


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: str, user: User = Depends(get_current_user)) -> JobDetail:
    detail = await get_job_detail(org_id=user.org_id, job_id=job_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return detail


@router.post("/{job_id}/jd", response_model=UploadResult)
async def upload_jd(
    job_id: str,
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    user: User = Depends(get_current_user),
) -> UploadResult:
    detail = await get_job_detail(org_id=user.org_id, job_id=job_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    pasted = (text or "").strip()
    if file is not None and file.filename:
        content = await file.read()
        filename = file.filename or "job-description"
        mime = file.content_type or "application/octet-stream"
    elif pasted:
        content = pasted.encode("utf-8")
        filename = "pasted-jd.txt"
        mime = "text/plain"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload a JD file or paste the text",
        )
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Job description is empty")
    try:
        return await store_and_extract(
            org_id=user.org_id,
            user_id=user.id,
            owner_type=DocumentOwnerType.job,
            owner_id=job_id,
            kind=DocumentKind.jd,
            filename=filename,
            mime=mime,
            content=content,
            max_bytes=settings.max_upload_bytes,
            job_id=job_id,
        )
    except UploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{job_id}/parse-jd", response_model=PipelineRunPublic)
async def parse_jd(job_id: str, user: User = Depends(get_current_user)) -> PipelineRunPublic:
    detail = await get_job_detail(org_id=user.org_id, job_id=job_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if not detail.jd or not detail.jd.extracted_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JD text is not extracted yet")
    if not settings.llm_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROQ_API_KEY is not configured. Add it to .env and restart the API.",
        )
    run = await start_parse(org_id=user.org_id, kind="jd", subject_type="job", subject_id=job_id)
    return PipelineRunPublic.model_validate(run)


@router.get("/{job_id}/requirements", response_model=list[RequirementPublic])
async def get_requirements(job_id: str, user: User = Depends(get_current_user)) -> list[RequirementPublic]:
    detail = await get_job_detail(org_id=user.org_id, job_id=job_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return await list_requirements(job_id=job_id)


@router.get("/{job_id}/matrix", response_model=MatrixResponse)
async def get_job_matrix(job_id: str, user: User = Depends(get_current_user)) -> MatrixResponse:
    matrix = await get_matrix(org_id=user.org_id, job_id=job_id)
    if matrix is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return matrix
