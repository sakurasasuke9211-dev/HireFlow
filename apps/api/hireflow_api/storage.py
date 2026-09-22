from __future__ import annotations

from pathlib import Path

from hireflow_api.config import settings

BUCKET = "hireflow"


class ObjectStore:
    async def put(self, key: str, data: bytes, content_type: str) -> None:
        raise NotImplementedError

    async def get(self, key: str) -> bytes:
        raise NotImplementedError


class LocalObjectStore(ObjectStore):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ValueError("invalid storage key")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self._path(key).write_bytes(data)

    async def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class S3ObjectStore(ObjectStore):
    def __init__(self) -> None:
        import boto3

        kwargs: dict = {"region_name": settings.s3_region}
        if settings.s3_endpoint_url:
            kwargs["endpoint_url"] = settings.s3_endpoint_url
        if settings.s3_access_key:
            kwargs["aws_access_key_id"] = settings.s3_access_key
            kwargs["aws_secret_access_key"] = settings.s3_secret_key
        self.client = boto3.client("s3", **kwargs)
        self.bucket = settings.s3_bucket
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.bucket)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    async def get(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()


class SupabaseObjectStore(ObjectStore):
    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await ensure_bucket()
        try:
            await self._upload(key, data, content_type)
        except Exception:
            await ensure_bucket(force=True)
            await self._upload(key, data, content_type)

    async def _upload(self, key: str, data: bytes, content_type: str) -> None:
        from hireflow_api.db import get_client

        client = await get_client()
        await client.storage.from_(BUCKET).upload(
            key,
            data,
            file_options={"content-type": content_type, "upsert": "true", "x-upsert": "true"},
        )

    async def get(self, key: str) -> bytes:
        from hireflow_api.db import get_client

        client = await get_client()
        return await client.storage.from_(BUCKET).download(key)


_store: ObjectStore | None = None


def get_store() -> ObjectStore:
    global _store
    if _store is None:
        if settings.supabase_configured:
            _store = SupabaseObjectStore()
        elif settings.uses_s3:
            _store = S3ObjectStore()
        else:
            _store = LocalObjectStore(settings.resolved_storage_dir())
    return _store


async def ensure_bucket(*, force: bool = False) -> None:
    if not settings.supabase_configured:
        return
    from hireflow_api.db import get_client

    client = await get_client()
    if not force:
        try:
            await client.storage.get_bucket(BUCKET)
            return
        except Exception:
            pass
    try:
        await client.storage.create_bucket(
            BUCKET,
            options={"public": False, "file_size_limit": int(settings.max_upload_bytes)},
        )
    except Exception:
        await client.storage.get_bucket(BUCKET)
