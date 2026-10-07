from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import CertificateStatus, JobStatus


class Recipient(BaseModel):
    """Per-recipient rules. Applied during processing so one bad row fails only itself."""

    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    course: str | None = Field(default=None, max_length=150)
    issue_date: date | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class JobCreate(BaseModel):
    """Request-level rules. Failing these rejects the whole request with a 422."""

    title: str = Field(min_length=1, max_length=200, description="Event or course the certificate is for")
    recipients: list[dict[str, Any]] = Field(min_length=1)


class CertificateOut(BaseModel):
    id: str
    position: int
    recipient: dict[str, Any]
    status: CertificateStatus
    error: str | None = None
    download_url: str | None = None


class JobSummary(BaseModel):
    id: str
    title: str
    status: JobStatus
    total: int
    generated: int
    failed: int
    pending: int
    created_at: datetime
    completed_at: datetime | None = None


class JobDetail(JobSummary):
    certificates: list[CertificateOut]
