from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response

from hireflow_api.auth import get_current_user
from hireflow_api.config import settings
from hireflow_api.models import User
from hireflow_api.services import (
    UploadError,
    advance_candidate_screen,
    create_candidate,
    get_candidate_public,
    get_job_detail,
    list_gaps,
    list_matches,
    screening_brief_file,
    start_match,
    start_parse,
    store_and_extract,
)
from hireflow_domain.enums import DocumentKind, DocumentOwnerType
from hireflow_domain.schemas import CandidatePublic, GapPublic, MatchResultPublic, PipelineRunPublic, ScreenStatus, UploadResult

router = APIRouter(tags=["candidates"])


@router.post("/jobs/{job_id}/candidates", response_model=CandidatePublic, status_code=status.HTTP_201_CREATED)
async def create_candidate_route(
    job_id: str,
    full_name: str = Form(...),
    email: str | None = Form(default=None),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> CandidatePublic:
    job = await get_job_detail(org_id=user.org_id, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    candidate = await create_candidate(
        org_id=user.org_id,
        job_id=job_id,
        full_name=full_name,
        email=email,
    )

    content = await file.read()
    try:
        await store_and_extract(
            org_id=user.org_id,
            user_id=user.id,
            owner_type=DocumentOwnerType.candidate,
            owner_id=candidate.id,
            kind=DocumentKind.resume,
            filename=file.filename or "resume",
            mime=file.content_type or "application/octet-stream",
            content=content,
            max_bytes=settings.max_upload_bytes,
            job_id=job_id,
            candidate_id=candidate.id,
        )
    except UploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    public = await get_candidate_public(org_id=user.org_id, candidate_id=candidate.id)
    assert public is not None
    return public


@router.get("/candidates/{candidate_id}", response_model=CandidatePublic)
async def get_candidate(candidate_id: str, user: User = Depends(get_current_user)) -> CandidatePublic:
    public = await get_candidate_public(org_id=user.org_id, candidate_id=candidate_id)
    if public is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    return public


@router.post("/candidates/{candidate_id}/resume", response_model=UploadResult)
async def upload_resume(
    candidate_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> UploadResult:
    public = await get_candidate_public(org_id=user.org_id, candidate_id=candidate_id)
    if public is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    content = await file.read()
    try:
        return await store_and_extract(
            org_id=user.org_id,
            user_id=user.id,
            owner_type=DocumentOwnerType.candidate,
            owner_id=candidate_id,
            kind=DocumentKind.resume,
            filename=file.filename or "resume",
            mime=file.content_type or "application/octet-stream",
            content=content,
            max_bytes=settings.max_upload_bytes,
            job_id=public.job_id,
            candidate_id=candidate_id,
        )
    except UploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/candidates/{candidate_id}/parse-resume", response_model=PipelineRunPublic)
async def parse_resume(candidate_id: str, user: User = Depends(get_current_user)) -> PipelineRunPublic:
    public = await get_candidate_public(org_id=user.org_id, candidate_id=candidate_id)
    if public is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    if not public.resume or not public.resume.extracted_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Resume text is not extracted yet")
    if not settings.llm_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROQ_API_KEY is not configured. Add it to .env and restart the API.",
        )
    run = await start_parse(
        org_id=user.org_id,
        kind="resume",
        subject_type="candidate",
        subject_id=candidate_id,
    )
    return PipelineRunPublic.model_validate(run)


@router.post("/candidates/{candidate_id}/reparse", response_model=PipelineRunPublic)
async def reparse_candidate(candidate_id: str, user: User = Depends(get_current_user)) -> PipelineRunPublic:
    """Re-run resume parsing (claims/profile) even when a profile already exists."""
    return await parse_resume(candidate_id, user)


@router.get("/candidates/{candidate_id}/profile", response_model=CandidatePublic)
async def get_profile(candidate_id: str, user: User = Depends(get_current_user)) -> CandidatePublic:
    public = await get_candidate_public(org_id=user.org_id, candidate_id=candidate_id)
    if public is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    return public


@router.post("/candidates/{candidate_id}/match", response_model=PipelineRunPublic)
async def match_candidate(candidate_id: str, user: User = Depends(get_current_user)) -> PipelineRunPublic:
    public = await get_candidate_public(org_id=user.org_id, candidate_id=candidate_id)
    if public is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    try:
        run = await start_match(org_id=user.org_id, candidate_id=candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PipelineRunPublic.model_validate(run)


@router.get("/candidates/{candidate_id}/matches", response_model=list[MatchResultPublic])
async def get_matches(candidate_id: str, user: User = Depends(get_current_user)) -> list[MatchResultPublic]:
    try:
        return await list_matches(org_id=user.org_id, candidate_id=candidate_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found") from None


@router.get("/candidates/{candidate_id}/gaps", response_model=list[GapPublic])
async def get_gaps(candidate_id: str, user: User = Depends(get_current_user)) -> list[GapPublic]:
    try:
        return await list_gaps(org_id=user.org_id, candidate_id=candidate_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found") from None


@router.post("/candidates/{candidate_id}/screen", response_model=ScreenStatus)
async def screen_candidate(
    candidate_id: str,
    force: bool = False,
    user: User = Depends(get_current_user),
) -> ScreenStatus:
    try:
        return await advance_candidate_screen(org_id=user.org_id, candidate_id=candidate_id, force=force)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/candidates/{candidate_id}/screening-brief")
async def download_screening_brief(candidate_id: str, user: User = Depends(get_current_user)) -> Response:
    try:
        filename, body = await screening_brief_file(org_id=user.org_id, candidate_id=candidate_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
