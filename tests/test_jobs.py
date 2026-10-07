import io
import zipfile

from app import certificate
from tests.conftest import recipient


def create_job(client, recipients, title="PyCon Workshop"):
    return client.post("/api/jobs", json={"title": title, "recipients": recipients})


# --- creating a job -------------------------------------------------------------------------

def test_create_job_returns_202_with_job_summary(client):
    resp = create_job(client, [recipient(1), recipient(2)])
    assert resp.status_code == 202
    body = resp.json()
    assert body["id"] and body["total"] == 2 and body["title"] == "PyCon Workshop"


def test_job_can_be_fetched_after_creation(client):
    job_id = create_job(client, [recipient(1)]).json()["id"]
    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == job_id


def test_unknown_job_returns_404(client):
    assert client.get("/api/jobs/doesnotexist").status_code == 404


# --- input validation -----------------------------------------------------------------------

def test_empty_recipient_list_is_rejected(client):
    assert create_job(client, []).status_code == 422


def test_missing_title_is_rejected(client):
    assert client.post("/api/jobs", json={"recipients": [recipient(1)]}).status_code == 422


def test_too_many_recipients_is_rejected(client):
    resp = create_job(client, [recipient(i) for i in range(51)])
    assert resp.status_code == 422


def test_invalid_recipients_fail_individually_with_reasons(client):
    resp = create_job(
        client,
        [
            recipient(1),
            {"name": "No Email"},
            recipient(3, email="not-an-email"),
            recipient(4, name="   "),
        ],
    )
    job = client.get(f"/api/jobs/{resp.json()['id']}").json()
    statuses = [c["status"] for c in job["certificates"]]
    assert statuses == ["GENERATED", "FAILED", "FAILED", "FAILED"]
    assert "email" in job["certificates"][1]["error"]
    assert "email" in job["certificates"][2]["error"]
    assert "name" in job["certificates"][3]["error"]


# --- certificate generation -----------------------------------------------------------------

def test_certificates_are_generated_as_pdfs(client):
    job = client.get(f"/api/jobs/{create_job(client, [recipient(1)]).json()['id']}").json()
    cert = job["certificates"][0]
    assert cert["status"] == "GENERATED" and cert["download_url"]
    pdf = client.get(cert["download_url"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_render_certificate_writes_pdf(tmp_path):
    from app.schemas import Recipient

    out = tmp_path / "nested" / "c.pdf"
    certificate.render_certificate(Recipient(name="Ada Lovelace", email="ada@example.com"), "Maths", out)
    assert out.read_bytes().startswith(b"%PDF")


# --- job status / progress ------------------------------------------------------------------

def test_completed_job_reports_counts(client):
    job = client.get(f"/api/jobs/{create_job(client, [recipient(i) for i in range(5)]).json()['id']}").json()
    assert job["status"] == "COMPLETED"
    assert (job["total"], job["generated"], job["failed"], job["pending"]) == (5, 5, 0, 0)
    assert job["completed_at"] is not None


def test_mixed_job_is_completed_with_errors(client):
    job = client.get(f"/api/jobs/{create_job(client, [recipient(1), {'name': 'x'}]).json()['id']}").json()
    assert job["status"] == "COMPLETED_WITH_ERRORS"
    assert (job["generated"], job["failed"]) == (1, 1)


def test_job_where_everything_fails_is_failed(client):
    job = client.get(f"/api/jobs/{create_job(client, [{'name': 'x'}, {}]).json()['id']}").json()
    assert job["status"] == "FAILED"
    assert job["failed"] == 2


# --- a failure while generating one certificate ---------------------------------------------

def test_render_failure_does_not_stop_other_certificates(client, monkeypatch):
    real = certificate.render_certificate

    def flaky(recipient_, title, path):
        if recipient_.name == "Person 2":
            raise RuntimeError("disk exploded")
        return real(recipient_, title, path)

    monkeypatch.setattr("app.processor.render_certificate", flaky)

    job = client.get(f"/api/jobs/{create_job(client, [recipient(1), recipient(2), recipient(3)]).json()['id']}").json()
    assert [c["status"] for c in job["certificates"]] == ["GENERATED", "FAILED", "GENERATED"]
    assert "disk exploded" in job["certificates"][1]["error"]
    assert job["certificates"][1]["download_url"] is None
    assert job["status"] == "COMPLETED_WITH_ERRORS"


def test_non_latin1_name_fails_only_that_certificate(client):
    job = client.get(f"/api/jobs/{create_job(client, [recipient(1), recipient(2, name='李小龍')]).json()['id']}").json()
    assert [c["status"] for c in job["certificates"]] == ["GENERATED", "FAILED"]


# --- retrieving generated certificates ------------------------------------------------------

def test_failed_certificate_cannot_be_downloaded(client):
    job = client.get(f"/api/jobs/{create_job(client, [{'name': 'x'}]).json()['id']}").json()
    resp = client.get(f"/api/jobs/{job['id']}/certificates/{job['certificates'][0]['id']}")
    assert resp.status_code == 409


def test_certificate_from_another_job_is_404(client):
    a = client.get(f"/api/jobs/{create_job(client, [recipient(1)]).json()['id']}").json()
    b = create_job(client, [recipient(2)]).json()
    assert client.get(f"/api/jobs/{b['id']}/certificates/{a['certificates'][0]['id']}").status_code == 404


def test_download_all_returns_zip_of_generated_certificates_only(client):
    job_id = create_job(client, [recipient(1), {'name': 'bad'}, recipient(3)]).json()["id"]
    resp = client.get(f"/api/jobs/{job_id}/download")
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert sorted(zf.namelist()) == ["certificate-1.pdf", "certificate-3.pdf"]


def test_download_all_with_nothing_generated_is_409(client):
    job_id = create_job(client, [{'name': 'bad'}]).json()["id"]
    assert client.get(f"/api/jobs/{job_id}/download").status_code == 409
