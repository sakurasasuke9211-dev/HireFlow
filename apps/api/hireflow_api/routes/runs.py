from fastapi import APIRouter, Depends, HTTPException, status

from hireflow_api.auth import get_current_user
from hireflow_api.models import User
from hireflow_api.services import get_run
from hireflow_domain.schemas import PipelineRunPublic

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}", response_model=PipelineRunPublic)
async def get_run_route(run_id: str, user: User = Depends(get_current_user)) -> PipelineRunPublic:
    run = await get_run(run_id)
    if run is None or run.org_id != user.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return PipelineRunPublic.model_validate(run)
