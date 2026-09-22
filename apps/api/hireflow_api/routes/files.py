from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from hireflow_api.auth import get_current_user
from hireflow_api.file_service import (
    chat_with_assistant,
    download_document_file,
    download_located_file,
    list_file_assistant_history,
    locate_org_files,
)
from hireflow_api.models import User
from hireflow_domain.schemas import (
    FileAssistantChatRequest,
    FileAssistantChatResponse,
    FileAssistantHistoryItem,
    FileLocatorQuery,
    FileLocatorResponse,
)

router = APIRouter(tags=["files"])


def _file_response(filename: str, body: bytes, mime: str) -> Response:
    return Response(
        content=body,
        media_type=f"{mime}; charset=utf-8" if mime.startswith("text/") else mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/files/locate", response_model=FileLocatorResponse)
async def locate_files(body: FileLocatorQuery, user: User = Depends(get_current_user)) -> FileLocatorResponse:
    return await locate_org_files(org_id=user.org_id, user_id=user.id, query=body.query)


@router.post("/files/chat", response_model=FileAssistantChatResponse)
async def file_assistant_chat(
    body: FileAssistantChatRequest,
    user: User = Depends(get_current_user),
) -> FileAssistantChatResponse:
    try:
        return await chat_with_assistant(org_id=user.org_id, user_id=user.id, body=body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/files/history", response_model=list[FileAssistantHistoryItem])
async def file_assistant_history(user: User = Depends(get_current_user)) -> list[FileAssistantHistoryItem]:
    return await list_file_assistant_history(org_id=user.org_id)


@router.get("/files/download")
async def download_file(
    locator: str = Query(..., min_length=3),
    user: User = Depends(get_current_user),
) -> Response:
    try:
        filename, body, mime = await download_located_file(org_id=user.org_id, locator=locator)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _file_response(filename, body, mime)


@router.get("/documents/{document_id}/download")
async def download_document(document_id: str, user: User = Depends(get_current_user)) -> Response:
    try:
        filename, body, mime = await download_document_file(org_id=user.org_id, document_id=document_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _file_response(filename, body, mime)
