"""End-to-end verification: API behavior + Supabase persistence."""
from __future__ import annotations

import asyncio
import json
import re
import sys
import urllib.error
import urllib.request

from hireflow_api.auth import create_access_token
from hireflow_api.db import fetch_many, fetch_one
from hireflow_api.services import screening_brief_file

BASE = "http://127.0.0.1:8000"
CANDIDATE_ID = "fa6abd37-eb9d-4fbb-80c2-191e89519453"


def http(method: str, path: str, token: str, data: dict | None = None) -> tuple[int, bytes]:
    headers = {"Authorization": f"Bearer {token}"}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


async def main() -> int:
    candidate = await fetch_one("candidates", id=CANDIDATE_ID)
    if candidate is None:
        print(f"FAIL: candidate {CANDIDATE_ID} not found")
        return 1
    org_id = candidate["org_id"]
    users = await fetch_many("users", org_id=org_id, limit=5)
    if not users:
        print("FAIL: no users in org")
        return 1
    user = users[0]
    token = create_access_token(user_id=user["id"], org_id=org_id)
    print(f"Using org {org_id[:8]}… user {user.get('email')}")

    candidate_id = CANDIDATE_ID
    print(f"Candidate: {candidate.get('full_name')} ({candidate_id})")

    results: list[tuple[str, bool, str]] = []

    # 1) Screening brief format (service + HTTP)
    _, brief_bytes = await screening_brief_file(org_id=org_id, candidate_id=candidate_id)
    brief_text = brief_bytes.decode("utf-8")
    no_confidence = "Confidence:" not in brief_text
    dup_count = len(re.findall(r"(?m)^No evidence found\.$", brief_text))
    per_req = len(re.findall(r"(?m)^### .+ — ", brief_text))
    no_dup = dup_count <= per_req
    results.append(("Screening brief: no Confidence field", no_confidence, f"found={not no_confidence}"))
    results.append(("Screening brief: no duplicate no-evidence", no_dup, f"lines={dup_count} reqs={per_req}"))

    code, raw = http("GET", f"/candidates/{candidate_id}/screening-brief", token)
    results.append(("HTTP screening-brief download", code == 200, f"status={code}"))

    # 2) File assistant page context
    chat_body = {
        "messages": [{"role": "user", "content": "What are the match and gaps?"}],
        "page_context": {
            "candidate_id": candidate_id,
            "candidate_name": candidate.get("full_name"),
            "job_id": candidate.get("job_id"),
            "job_title": None,
        },
    }
    code, raw = http("POST", "/files/chat", token, chat_body)
    chat = json.loads(raw) if code == 200 else {}
    scoped = code == 200 and len(chat.get("hits", [])) == 1
    hit_locator = chat.get("hits", [{}])[0].get("locator") if chat.get("hits") else None
    scoped = scoped and hit_locator == f"screening:{candidate_id}"
    has_answer = bool(chat.get("answer"))
    results.append(("Assistant: scoped to open candidate", scoped, f"hits={len(chat.get('hits', []))} locator={hit_locator}"))
    results.append(("Assistant: returns match/gaps content", has_answer, "answer empty" if not has_answer else "ok"))

    # 3) Interview brief download + DB report row
    reports_before = await fetch_many("reports", org_id=org_id, candidate_id=candidate_id, kind="interview_brief")
    count_before = len(reports_before)
    code, raw = http("GET", f"/candidates/{candidate_id}/interview-brief", token)
    reports_after = await fetch_many("reports", org_id=org_id, candidate_id=candidate_id, kind="interview_brief")
    plan = await fetch_one("interview_plans", org_id=org_id, candidate_id=candidate_id)
    brief_report_id = plan.get("brief_report_id") if plan else None
    report_row = await fetch_one("reports", id=brief_report_id, org_id=org_id) if brief_report_id else None
    results.append(("HTTP interview-brief download", code == 200, f"status={code} bytes={len(raw)}"))
    results.append(
        (
            "DB: interview plan linked to brief report",
            brief_report_id is not None and report_row is not None,
            f"brief_report_id={brief_report_id}",
        )
    )
    results.append(
        (
            "DB: interview brief stored in reports",
            len(reports_after) >= count_before and len(reports_after) > 0,
            f"reports={len(reports_after)} (was {count_before})",
        )
    )

    # 4) Match results persisted in DB
    matches = await fetch_many("match_results", candidate_id=candidate_id)
    results.append(("DB: match_results rows exist", len(matches) > 0, f"count={len(matches)}"))

    # 5) File assistant audit log
    code, raw = http("GET", "/files/history", token)
    history = json.loads(raw) if code == 200 else []
    results.append(("DB: file_assistant_requests logged", len(history) > 0, f"history={len(history)}"))

    print("\n=== Verification results ===")
    failed = 0
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{status}] {name} — {detail}")

    if failed:
        print(f"\n{failed} check(s) failed.")
        return 1
    print("\nAll checks passed — changes work and data is stored in Supabase.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
