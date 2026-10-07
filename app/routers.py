import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app import config, database
from app.database import get_db
from app.models import Certificate, CertificateStatus, Job
from app.processor import process_job
from app.schemas import CertificateOut, JobCreate, JobDetail, JobSummary

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _summary(job: Job) -> dict:
    counts = {s: 0 for s in CertificateStatus}
    for c in job.certificates:
        counts[c.status] += 1
    return {
        "id": job.id,
        "title": job.title,
        "status": job.status,
        "total": len(job.certificates),
        "generated": counts[CertificateStatus.GENERATED],
        "failed": counts[CertificateStatus.FAILED],
        "pending": counts[CertificateStatus.PENDING],
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }


def _certificate_out(job_id: str, cert: Certificate) -> CertificateOut:
    return CertificateOut(
        id=cert.id,
        position=cert.position,
        recipient=cert.recipient,
        status=cert.status,
        error=cert.error,
        download_url=(
            f"/api/jobs/{job_id}/certificates/{cert.id}"
            if cert.status == CertificateStatus.GENERATED
            else None
        ),
    )


def _get_job_or_404(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.post("", response_model=JobSummary, status_code=status.HTTP_202_ACCEPTED)
def create_job(payload: JobCreate, background: BackgroundTasks, db: Session = Depends(get_db)):
    if len(payload.recipients) > config.MAX_RECIPIENTS_PER_JOB:
        raise HTTPException(
            422,
            f"A job may contain at most {config.MAX_RECIPIENTS_PER_JOB} recipients",
        )
    job = Job(title=payload.title.strip())
    job.certificates = [
        Certificate(position=i, recipient=r) for i, r in enumerate(payload.recipients)
    ]
    db.add(job)
    db.commit()
    background.add_task(process_job, job.id, database.SessionLocal)
    return _summary(job)


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = _get_job_or_404(db, job_id)
    return {**_summary(job), "certificates": [_certificate_out(job.id, c) for c in job.certificates]}


@router.get("/{job_id}/certificates/{certificate_id}")
def download_certificate(job_id: str, certificate_id: str, db: Session = Depends(get_db)):
    cert = db.get(Certificate, certificate_id)
    if cert is None or cert.job_id != job_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found")
    if cert.status != CertificateStatus.GENERATED or not cert.file_path or not Path(cert.file_path).exists():
        raise HTTPException(status.HTTP_409_CONFLICT, f"Certificate is not available (status: {cert.status.value})")
    return FileResponse(cert.file_path, media_type="application/pdf", filename=f"certificate-{cert.position + 1}.pdf")


@router.get("/{job_id}/download")
def download_all(job_id: str, db: Session = Depends(get_db)):
    job = _get_job_or_404(db, job_id)
    ready = [c for c in job.certificates if c.status == CertificateStatus.GENERATED and c.file_path]
    if not ready:
        raise HTTPException(status.HTTP_409_CONFLICT, "No generated certificates available yet")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for c in ready:
            zf.write(c.file_path, f"certificate-{c.position + 1}.pdf")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="certificates-{job.id}.zip"'},
    )
