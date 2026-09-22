from fastapi import APIRouter, Depends, HTTPException, status

from hireflow_api.auth import get_current_user
from hireflow_api.models import User
from hireflow_api.services import patch_gap
from hireflow_domain.schemas import GapPatch, GapPublic

router = APIRouter(tags=["gaps"])


@router.patch("/gaps/{gap_id}", response_model=GapPublic)
async def update_gap(gap_id: str, body: GapPatch, user: User = Depends(get_current_user)) -> GapPublic:
    try:
        return await patch_gap(org_id=user.org_id, gap_id=gap_id, body=body)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gap not found") from None
