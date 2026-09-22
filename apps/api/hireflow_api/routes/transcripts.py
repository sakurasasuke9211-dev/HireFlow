from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from hireflow_api.auth import get_current_user
from hireflow_api.config import settings
from hireflow_api.models import User
from hireflow_api.services import (
    UploadError,
    create_transcript,
    get_candidate_public,
    get_transcript,
    list_probes,
    list_transcripts,
    patch_transcript_turn,
    start_analyze_unless_active,
)
from hireflow_domain.enums import TranscriptSource
from hireflow_domain.schemas import PipelineRunPublic, ProbeResultPublic, TranscriptDetail, TranscriptPublic, TranscriptTurnPatch, TranscriptTurnPublic

router = APIRouter(tags=["transcripts"])


@router.post("/candidates/{candidate_id}/transcripts", response_model=TranscriptPublic, status_code=status.HTTP_201_CREATED)
async def upload_transcript(
    candidate_id: str,
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    user: User = Depends(get_current_user),
) -> TranscriptPublic:
    public = await get_candidate_public(org_id=user.org_id, candidate_id=candidate_id)
    if public is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    pasted = (text or "").strip()
    if file is not None and file.filename:
        content = await file.read()
        filename = file.filename or "transcript.txt"
        mime = file.content_type or "application/octet-stream"
        source = TranscriptSource.file
    elif pasted:
        content = pasted.encode("utf-8")
        filename = "pasted-transcript.txt"
        mime = "text/plain"
        source = TranscriptSource.paste
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload a transcript file or paste the text")
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transcript is empty")
    try:
        return await create_transcript(
            org_id=user.org_id,
            user_id=user.id,
            candidate_id=candidate_id,
            filename=filename,
            mime=mime,
            content=content,
            source=source,
            max_bytes=settings.max_upload_bytes,
        )
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found") from None
    except UploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/candidates/{candidate_id}/transcripts", response_model=list[TranscriptPublic])
async def read_transcripts(candidate_id: str, user: User = Depends(get_current_user)) -> list[TranscriptPublic]:
    try:
        return await list_transcripts(org_id=user.org_id, candidate_id=candidate_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found") from None


@router.get("/transcripts/{transcript_id}", response_model=TranscriptDetail)
async def read_transcript(transcript_id: str, user: User = Depends(get_current_user)) -> TranscriptDetail:
    try:
        return await get_transcript(org_id=user.org_id, transcript_id=transcript_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found") from None


@router.post("/transcripts/{transcript_id}/analyze", response_model=PipelineRunPublic)
async def analyze_transcript_route(transcript_id: str, user: User = Depends(get_current_user)) -> PipelineRunPublic:
    try:
        run = await start_analyze_unless_active(org_id=user.org_id, transcript_id=transcript_id)
        if run is None:
            raise ValueError("Transcript text is not extracted yet")
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PipelineRunPublic.model_validate(run)


@router.get("/transcripts/{transcript_id}/probes", response_model=list[ProbeResultPublic])
async def read_probes(transcript_id: str, user: User = Depends(get_current_user)) -> list[ProbeResultPublic]:
    try:
        return await list_probes(org_id=user.org_id, transcript_id=transcript_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found") from None


@router.patch("/transcript-turns/{turn_id}", response_model=TranscriptTurnPublic)
async def update_transcript_turn(
    turn_id: str,
    body: TranscriptTurnPatch,
    user: User = Depends(get_current_user),
) -> TranscriptTurnPublic:
    try:
        return await patch_transcript_turn(org_id=user.org_id, turn_id=turn_id, body=body)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turn not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
