from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from hireflow_api.auth import get_current_user
from hireflow_api.models import User
from hireflow_api.services import (
    download_interview_brief,
    get_interview_plan,
    patch_planned_question,
    start_plan_unless_active,
)
from hireflow_domain.schemas import InterviewPlanResponse, PipelineRunPublic, PlannedQuestionPatch, PlannedQuestionPublic

router = APIRouter(tags=["interview-plan"])


@router.post("/candidates/{candidate_id}/interview-plan", response_model=PipelineRunPublic)
async def create_interview_plan(candidate_id: str, user: User = Depends(get_current_user)) -> PipelineRunPublic:
    try:
        run = await start_plan_unless_active(org_id=user.org_id, candidate_id=candidate_id)
        if run is None:
            raise ValueError("Match the resume to the JD before generating an interview plan")
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PipelineRunPublic.model_validate(run)


@router.get("/candidates/{candidate_id}/interview-plan", response_model=InterviewPlanResponse)
async def read_interview_plan(candidate_id: str, user: User = Depends(get_current_user)) -> InterviewPlanResponse:
    try:
        return await get_interview_plan(org_id=user.org_id, candidate_id=candidate_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found") from None


@router.get("/candidates/{candidate_id}/interview-brief")
async def download_candidate_interview_brief(candidate_id: str, user: User = Depends(get_current_user)) -> Response:
    try:
        filename, body, mime = await download_interview_brief(org_id=user.org_id, candidate_id=candidate_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(
        content=body,
        media_type=f"{mime}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/planned-questions/{question_id}", response_model=PlannedQuestionPublic)
async def update_planned_question(
    question_id: str,
    body: PlannedQuestionPatch,
    user: User = Depends(get_current_user),
) -> PlannedQuestionPublic:
    try:
        return await patch_planned_question(org_id=user.org_id, question_id=question_id, body=body)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found") from None
