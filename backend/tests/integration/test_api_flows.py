"""End-to-end API flows using SQLite and the local storage backend."""
from __future__ import annotations

from datetime import date, timedelta


def _primary_pdf(pdf_factory, amount: int = 500):
    future = date.today() + timedelta(days=30)
    deadline = f"{future.day} {future.strftime('%B %Y')}"
    return pdf_factory(
        [
            f"Late fee of INR {amount} will apply after {deadline}.",
            f"Last date for exam form submission is {deadline}.",
            "Students must maintain 75% attendance.",
        ]
    )


def _upload(
    client,
    headers,
    pdf: bytes,
    *,
    title: str = "Fee and Exam Notice",
    issued_on: str | None = None,
):
    response = client.post(
        "/api/admin/notices",
        headers=headers,
        files={"file": ("notice.pdf", pdf, "application/pdf")},
        data={
            "title": title,
            "issuer": "Examination Cell",
            "issued_on": issued_on or (date.today() - timedelta(days=5)).isoformat(),
            "category": "exam",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health_and_openapi(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"
    assert health.json()["gemini_configured"] is False

    ready = client.get("/health/ready")
    assert ready.status_code == 200

    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/api/ask" in paths
    assert "/api/admin/facts/{fact_id}/approve" in paths
    assert "/api/facts/{fact_id}/source" in paths
    assert "/api/calendar.ics" in paths


def test_register_login_and_profile(client):
    registered = client.post(
        "/api/auth/register",
        json={
            "email": "student@example.com",
            "password": "Password123",
            "full_name": "Student One",
            "profile": {"course": "B.Tech", "semester": 4, "academic_year": "2026-2027"},
        },
    )
    assert registered.status_code == 201, registered.text
    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["student_profile"]["academic_year"] == "2026-27"

    updated = client.patch(
        "/api/auth/me/profile",
        headers=headers,
        json={"course": "B.Tech CSE", "semester": 5},
    )
    assert updated.status_code == 200
    assert updated.json()["student_profile"]["course"] == "B.Tech CSE"
    assert updated.json()["student_profile"]["semester"] == 5

    duplicate = client.post(
        "/api/auth/register",
        json={"email": "student@example.com", "password": "Password123"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"

    bad_login = client.post(
        "/api/auth/login", json={"email": "student@example.com", "password": "wrong-password"}
    )
    assert bad_login.status_code == 401

    assert client.get("/api/auth/me").status_code == 401


def test_admin_guard_and_upload_approval_answer(
    client, admin_headers, register_student, pdf_factory, approve_candidates
):
    admin = admin_headers()
    student = register_student()
    assert client.get("/api/admin/dashboard", headers=student).status_code == 403

    uploaded = _upload(client, admin, _primary_pdf(pdf_factory))
    assert uploaded["extracted_fact_count"] == 3
    assert uploaded["requires_manual_review"] is False
    assert uploaded["notice"]["status"] == "draft"

    candidates = client.get(
        "/api/admin/facts", headers=admin, params={"status": "candidate"}
    ).json()["items"]
    fee = next(fact for fact in candidates if fact["fact_key"] == "fee.late_fee")
    assert fee["source_bbox"] is not None
    assert fee["source_precision"] == "exact"

    approve_candidates(admin, notice_id=uploaded["notice"]["id"])

    answer = client.post(
        "/api/ask", headers=student, json={"question": "What is the late fee?"}
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["state"] == "verified"
    assert body["verified"] is True
    assert "500" in body["answer"]
    assert body["fact_ids"]
    assert body["citations"][0]["notice_title"] == "Fee and Exam Notice"
    assert body["citations"][0]["source_precision"] == "exact"

    deadlines = client.get("/api/deadlines", headers=student)
    assert deadlines.status_code == 200
    assert any(item["fact_key"] == "date.exam_form_last_date" for item in deadlines.json())

    calendar = client.get("/api/calendar", headers=student)
    assert calendar.status_code == 200
    assert calendar.json()["events"]

    ics = client.get("/api/calendar/ics", headers=student)
    assert ics.status_code == 200
    assert "BEGIN:VCALENDAR" in ics.text
    assert "BEGIN:VEVENT" in ics.text

    legacy_ics = client.get("/api/calendar.ics", headers=student)
    assert legacy_ics.status_code == 200
    assert "BEGIN:VCALENDAR" in legacy_ics.text


def test_published_static_question_is_cited(
    client, admin_headers, register_student, pdf_factory, approve_candidates
):
    admin = admin_headers()
    student = register_student()
    uploaded = _upload(client, admin, _primary_pdf(pdf_factory))
    approve_candidates(admin, notice_id=uploaded["notice"]["id"])

    draft_answer = client.post(
        "/api/ask", headers=student, json={"question": "What is the attendance policy?"}
    )
    assert draft_answer.status_code == 200
    assert draft_answer.json()["state"] == "unavailable"

    published = client.post(
        f"/api/admin/notices/{uploaded['notice']['id']}/publish", headers=admin
    )
    assert published.status_code == 200
    assert published.json()["facts_published"] == 3

    notices = client.get("/api/notices")
    assert notices.status_code == 200
    assert notices.json()["total"] == 1

    answer = client.post(
        "/api/ask", headers=student, json={"question": "What is the attendance policy?"}
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["state"] == "static_grounded"
    assert body["verified"] is True
    assert "75%" in body["answer"]
    assert body["citations"][0]["document_name"] == "notice.pdf"


def test_duplicate_document_attaches_source_instead_of_new_ledger_fact(
    client, admin_headers, register_student, pdf_factory, approve_candidates
):
    admin = admin_headers()
    register_student()
    first = _upload(client, admin, _primary_pdf(pdf_factory))
    approve_candidates(admin, notice_id=first["notice"]["id"])

    second = _upload(client, admin, _primary_pdf(pdf_factory), title="Duplicate Copy")
    assert second["extracted_fact_count"] == 3
    rejected = client.get(
        "/api/admin/facts", headers=admin, params={"status": "rejected"}
    ).json()["items"]
    assert len(rejected) == 3
    assert all("Duplicate" in (item["rejection_reason"] or "") for item in rejected)
    rejected_detail = client.get(
        f"/api/admin/facts/{rejected[0]['id']}", headers=admin
    ).json()
    assert rejected_detail["versions"][-1]["change_type"] == "rejected"

    active_fee = next(
        item
        for item in client.get(
            "/api/admin/facts",
            headers=admin,
            params={"status": "active", "fact_key": "fee.late_fee"},
        ).json()["items"]
    )
    detail = client.get(f"/api/admin/facts/{active_fee['id']}", headers=admin)
    assert detail.status_code == 200
    assert len(detail.json()["sources"]) == 2


def test_newer_notice_supersedes_after_admin_conflict_resolution(
    client,
    admin_headers,
    register_student,
    pdf_factory,
    approve_candidates,
):
    admin = admin_headers()
    student = register_student()

    old = _upload(
        client,
        admin,
        pdf_factory(["Late fee of INR 500 will apply after 20 November 2026."]),
        title="Old Fee Notice",
        issued_on="2026-11-01",
    )
    approve_candidates(admin, notice_id=old["notice"]["id"])

    new = _upload(
        client,
        admin,
        pdf_factory(["Late fee of INR 700 will apply after 20 November 2026."]),
        title="New Fee Notice",
        issued_on="2026-11-05",
    )
    candidates = client.get(
        "/api/admin/facts",
        headers=admin,
        params={"status": "candidate", "notice_id": new["notice"]["id"]},
    ).json()["items"]
    assert len(candidates) == 1
    candidate = candidates[0]

    blocked = client.post(
        f"/api/admin/facts/{candidate['id']}/approve", headers=admin, json={}
    )
    assert blocked.status_code == 409

    conflicts = client.get(
        "/api/admin/conflicts", headers=admin, params={"status": "pending"}
    ).json()["items"]
    conflict = next(item for item in conflicts if item["kind"] == "supersedes")
    resolved = client.post(
        f"/api/admin/conflicts/{conflict['id']}/resolve",
        headers=admin,
        json={"resolution": "approve_new", "note": "newer notice wins"},
    )
    assert resolved.status_code == 200, resolved.text
    audit_logs = client.get(
        "/api/admin/audit-logs",
        headers=admin,
        params={"action": "conflict.resolved"},
    ).json()
    assert audit_logs["total"] >= 1
    assert any(item["target_id"] == conflict["id"] for item in audit_logs["items"])

    answer = client.post(
        "/api/ask", headers=student, json={"question": "What is the late fee?"}
    ).json()
    assert answer["state"] == "verified"
    assert "700" in answer["answer"]
    assert answer["supersession"]["replaces_value_text"] == "INR 500"

    changes = client.get("/api/changes", headers=student)
    assert changes.status_code == 200
    assert any(item["old_value"] == "INR 500" and item["new_value"] == "INR 700" for item in changes.json())


def test_ask_and_deadlines_normalize_long_academic_year(
    client, register_student, seed_ledger
):
    student = register_student()
    future = date.today() + timedelta(days=20)
    seed_ledger(
        fact_key="fee.hostel_fee",
        value_text="INR 1200",
        value_number=1200.0,
        category="fee",
        scope={"academic_year": "2026-27"},
    )
    seed_ledger(
        fact_key="date.exam_date",
        value_text=future.strftime("%d %b %Y"),
        value_number=None,
        value_date=future,
        category="date",
        scope={"academic_year": "2026-27"},
    )

    answer = client.post(
        "/api/ask",
        headers=student,
        json={"question": "What is the hostel fee for 2026-2027?"},
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["state"] == "verified"
    assert "1200" in answer.json()["answer"]

    deadlines = client.get(
        "/api/deadlines", headers=student, params={"academic_year": "2026-2027"}
    )
    assert deadlines.status_code == 200
    assert any(item["fact_key"] == "date.exam_date" for item in deadlines.json())


def test_fact_source_endpoint_returns_published_notice_metadata(client, seed_ledger):
    fact = seed_ledger()
    response = client.get(f"/api/facts/{fact.id}/source")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fact_id"] == fact.id
    assert body["notice_id"] == fact.notice_id
    assert body["notice_title"] == "Seeded Notice"
    assert body["page_number"] == 1
    assert body["file_url"] == f"/api/notices/{fact.notice_id}/file"


def test_expired_candidate_cannot_be_approved(client, admin_headers, seed_ledger):
    admin = admin_headers()
    fact = seed_ledger(
        status="candidate",
        effective_to=date.today() - timedelta(days=1),
    )
    response = client.post(
        f"/api/admin/facts/{fact.id}/approve", headers=admin, json={}
    )
    assert response.status_code == 422
    assert "expired" in response.json()["error"]["message"].lower()


def test_editing_candidate_to_duplicate_does_not_block_active_answer(
    client, admin_headers, register_student, pdf_factory, approve_candidates
):
    admin = admin_headers()
    student = register_student()
    old = _upload(
        client,
        admin,
        pdf_factory(["Late fee of INR 500 will apply after 20 November 2026."]),
        title="Old Fee Notice",
        issued_on="2026-11-01",
    )
    approve_candidates(admin, notice_id=old["notice"]["id"])

    new = _upload(
        client,
        admin,
        pdf_factory(["Late fee of INR 700 will apply after 20 November 2026."]),
        title="New Fee Notice",
        issued_on="2026-11-05",
    )
    candidate = client.get(
        "/api/admin/facts",
        headers=admin,
        params={"status": "candidate", "notice_id": new["notice"]["id"]},
    ).json()["items"][0]
    edited = client.patch(
        f"/api/admin/facts/{candidate['id']}",
        headers=admin,
        json={"value_json": {"amount": 500, "currency": "INR"}, "value_text": "INR 500", "value_number": 500},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "candidate"

    answer = client.post(
        "/api/ask", headers=student, json={"question": "What is the late fee?"}
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["state"] == "verified"
    assert "500" in answer.json()["answer"]


def test_dispute_dismiss_records_rejection_snapshot(
    client, admin_headers, seed_ledger, pdf_factory
):
    admin = admin_headers()
    seed_ledger(
        value_text="INR 500",
        value_number=500.0,
        issued_on=date(2026, 11, 10),
    )
    uploaded = _upload(
        client,
        admin,
        pdf_factory(["Late fee of INR 700 will apply after 20 November 2026."]),
        title="Same Day Fee Notice",
        issued_on="2026-11-10",
    )
    candidate = client.get(
        "/api/admin/facts",
        headers=admin,
        params={"status": "disputed", "notice_id": uploaded["notice"]["id"]},
    ).json()["items"][0]
    conflicts = client.get(
        "/api/admin/conflicts",
        headers=admin,
        params={"status": "pending", "kind": "disputed"},
    ).json()["items"]
    conflict = next(item for item in conflicts if item["candidate_fact_id"] == candidate["id"])

    dismissed = client.post(
        f"/api/admin/conflicts/{conflict['id']}/resolve",
        headers=admin,
        json={"resolution": "dismiss", "note": "Duplicate rumor"},
    )
    assert dismissed.status_code == 200, dismissed.text

    detail = client.get(
        f"/api/admin/facts/{candidate['id']}", headers=admin
    ).json()
    assert detail["status"] == "rejected"
    assert detail["versions"][-1]["change_type"] == "rejected"


def test_unanswered_question_is_aggregated_without_user_identity(client, admin_headers):
    admin = admin_headers()
    first = client.post("/api/ask", json={"question": "What is the late fee?"})
    second = client.post("/api/ask", json={"question": "What is the late fee?"})
    assert first.status_code == 200
    assert first.json()["state"] == "unavailable"
    assert second.json()["unanswered_logged"] is True

    open_rows = client.get("/api/admin/unanswered", headers=admin).json()["items"]
    assert len(open_rows) == 1
    row = open_rows[0]
    assert row["occurrence_count"] == 2
    assert "student" not in row
    assert not any(key in row for key in ("user_id", "email", "ip_address"))

    resolved = client.post(
        f"/api/admin/unanswered/{row['id']}/resolve",
        headers=admin,
        json={"status": "resolved", "note": "answered by phone"},
    )
    assert resolved.status_code == 200
    assert client.get("/api/admin/unanswered", headers=admin).json()["total"] == 0


def test_expired_fact_returns_outdated_warning(client, register_student, seed_ledger):
    student = register_student()
    seed_ledger(
        effective_to=date.today() - timedelta(days=1),
        value_text="INR 500",
    )
    answer = client.post(
        "/api/ask", headers=student, json={"question": "What is the late fee?"}
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["state"] == "outdated"
    assert body["verified"] is False
    assert "INR 500" in body["answer"]
    assert body["validity"]["is_current"] is False


def test_disputed_fact_abstains(client, register_student, seed_ledger):
    student = register_student()
    seed_ledger(status="disputed", value_text="INR 500")
    answer = client.post(
        "/api/ask", headers=student, json={"question": "What is the late fee?"}
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["state"] == "disputed"
    assert body["verified"] is False
    assert "INR 500" in body["answer"]
    assert body["citations"]


def test_rejects_non_pdf_upload(client, admin_headers):
    admin = admin_headers()
    response = client.post(
        "/api/admin/notices",
        headers=admin,
        files={"file": ("notice.pdf", b"not a pdf", "application/pdf")},
        data={"title": "Bad upload"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_upload"
