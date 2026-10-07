"""Storage of user-uploaded files."""

from pydantic import BaseModel

from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import Blob


class BlobTooLargeError(ValueError):
    """Raised when an upload exceeds the configured size limit."""


class BlobNotFoundError(LookupError):
    """Raised when a blob id does not exist."""


class BlobOut(BaseModel):
    """Descriptor of a stored blob."""

    id: str
    media_type: str
    filename: str | None
    size: int


class BlobService:
    """Stores uploaded bytes in the database, up to ``max_bytes`` each."""

    def __init__(self, db: Database, max_bytes: int) -> None:
        self._db = db
        self.max_bytes = max_bytes

    async def put(self, data: bytes, media_type: str, filename: str | None) -> BlobOut:
        """Store ``data`` and return its descriptor.

        An empty ``media_type`` is stored as ``application/octet-stream``.

        Raises:
            BlobTooLargeError: if ``data`` is longer than ``max_bytes``.
        """
        if len(data) > self.max_bytes:
            raise BlobTooLargeError(f"file is larger than {self.max_bytes} bytes")
        blob = Blob(
            media_type=media_type or "application/octet-stream",
            filename=filename,
            size=len(data),
            data=data,
        )
        async with self._db.sessions() as session:
            session.add(blob)
            await session.commit()
        return BlobOut(id=blob.id, media_type=blob.media_type, filename=filename, size=blob.size)

    async def get(self, blob_id: str) -> Blob | None:
        """Return the stored blob, or None."""
        async with self._db.sessions() as session:
            return await session.get(Blob, blob_id)

    async def lookup(self, blob_id: str) -> tuple[bytes, str, str | None]:
        """Return ``(data, media_type, filename)`` of a blob.

        Raises:
            BlobNotFoundError: if the blob does not exist.
        """
        blob = await self.get(blob_id)
        if blob is None:
            raise BlobNotFoundError(f"uploaded file {blob_id} not found")
        return blob.data, blob.media_type, blob.filename
