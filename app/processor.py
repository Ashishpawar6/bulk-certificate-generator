import logging
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app import config
from app.certificate import render_certificate
from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import Recipient

logger = logging.getLogger(__name__)


def _validation_message(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'recipient'}: {e['msg']}" for e in exc.errors())


def _process_certificate(cert: Certificate, title: str) -> None:
    try:
        recipient = Recipient.model_validate(cert.recipient)
    except ValidationError as exc:
        cert.status = CertificateStatus.FAILED
        cert.error = f"Invalid recipient: {_validation_message(exc)}"
        return

    path = config.STORAGE_DIR / cert.job_id / f"{cert.id}.pdf"
    try:
        render_certificate(recipient, title, path)
    except Exception as exc:  # isolate any rendering failure to this certificate
        logger.exception("Certificate %s failed", cert.id)
        cert.status = CertificateStatus.FAILED
        cert.error = f"Generation failed: {exc}"
        return

    cert.status = CertificateStatus.GENERATED
    cert.file_path = str(path)


def process_job(job_id: str, session_factory: sessionmaker[Session]) -> None:
    """Generate every certificate in a job. Runs as a background task with its own session."""
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            job.status = JobStatus.PROCESSING
            db.commit()

            for cert in job.certificates:
                _process_certificate(cert, job.title)
                db.commit()  # commit per certificate so progress is visible while running

            failed = sum(c.status == CertificateStatus.FAILED for c in job.certificates)
            if failed == 0:
                job.status = JobStatus.COMPLETED
            elif failed == len(job.certificates):
                job.status = JobStatus.FAILED
            else:
                job.status = JobStatus.COMPLETED_WITH_ERRORS
        except Exception:
            logger.exception("Job %s crashed", job_id)
            db.rollback()
            job = db.get(Job, job_id)
            job.status = JobStatus.FAILED
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
