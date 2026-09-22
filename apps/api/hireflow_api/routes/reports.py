from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from hireflow_api.auth import get_current_user
from hireflow_api.models import User
from hireflow_api.services import (
    download_report_file,
    get_evidence_report,
    record_decision,
    start_report_unless_active,
)
from hireflow_domain.schemas import DecisionCreate, DecisionPublic, EvidenceReportResponse, PipelineRunPublic

router = APIRouter(tags=["reports"])


@router.post("/candidates/{candidate_id}/report", response_model=PipelineRunPublic)
async def create_evidence_report(candidate_id: str, user: User = Depends(get_current_user)) -> PipelineRunPublic:
    try:
        run = await start_report_unless_active(org_id=user.org_id, candidate_id=candidate_id)
        if run is None:
            raise ValueError("Match the resume to the JD before generating an evidence report")
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PipelineRunPublic.model_validate(run)


@router.get("/candidates/{candidate_id}/report", response_model=EvidenceReportResponse)
async def read_evidence_report(candidate_id: str, user: User = Depends(get_current_user)) -> EvidenceReportResponse:
    try:
        return await get_evidence_report(org_id=user.org_id, candidate_id=candidate_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found") from None


@router.get("/reports/{report_id}/download")
async def download_report(report_id: str, user: User = Depends(get_current_user)) -> Response:
    try:
        filename, body, mime = await download_report_file(org_id=user.org_id, report_id=report_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(
        content=body,
        media_type=f"{mime}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/reports/{report_id}/decision", response_model=DecisionPublic)
async def create_decision(
    report_id: str,
    body: DecisionCreate,
    user: User = Depends(get_current_user),
) -> DecisionPublic:
    try:
        return await record_decision(org_id=user.org_id, user_id=user.id, report_id=report_id, body=body)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
