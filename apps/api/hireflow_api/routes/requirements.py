from fastapi import APIRouter, Depends, HTTPException, Response, status

from hireflow_api.auth import get_current_user
from hireflow_api.models import User
from hireflow_api.services import patch_requirement
from hireflow_domain.schemas import RequirementPatch, RequirementPublic

router = APIRouter(tags=["requirements"])


@router.patch("/requirements/{requirement_id}", response_model=RequirementPublic)
async def update_requirement(
    requirement_id: str,
    body: RequirementPatch,
    user: User = Depends(get_current_user),
):
    try:
        result = await patch_requirement(org_id=user.org_id, requirement_id=requirement_id, body=body)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found") from None
    if body.dropped:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return result
