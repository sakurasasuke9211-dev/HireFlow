import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from hireflow_api.auth import create_access_token, get_current_user, hash_password, verify_password
from hireflow_api.db import fetch_one, insert_row
from hireflow_api.models import Org, User, utcnow
from hireflow_domain.schemas import AuthToken, LoginRequest, RegisterRequest, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthToken)
async def register(body: RegisterRequest) -> AuthToken:
    existing = await fetch_one("users", email=body.email.lower())
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    org = Org(id=str(uuid.uuid4()), name=body.org_name.strip(), created_at=utcnow())
    await insert_row("orgs", org)
    user = User(
        id=str(uuid.uuid4()),
        org_id=org.id,
        email=body.email.lower().strip(),
        name=body.name.strip(),
        password_hash=hash_password(body.password),
        role="recruiter",
        created_at=utcnow(),
    )
    stored = User.model_validate(await insert_row("users", user))
    token = create_access_token(user_id=stored.id, org_id=stored.org_id)
    return AuthToken(access_token=token, user=UserPublic.model_validate(stored))


@router.post("/login", response_model=AuthToken)
async def login(body: LoginRequest) -> AuthToken:
    row = await fetch_one("users", email=body.email.lower().strip())
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    user = User.model_validate(row)
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    token = create_access_token(user_id=user.id, org_id=user.org_id)
    return AuthToken(access_token=token, user=UserPublic.model_validate(user))


@router.get("/me", response_model=UserPublic)
async def me(user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(user)
