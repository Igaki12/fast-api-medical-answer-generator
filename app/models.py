from __future__ import annotations

from typing import Optional

from pydantic import BaseModel # type: ignore


class GenerateResponse(BaseModel):
    job_id: str
    status: str


class DownloadStatusResponse(BaseModel):
    job_id: str
    status: str
    message: Optional[str] = None
