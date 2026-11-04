#!/usr/bin/env python3
"""
Ask the production copilot a list of questions and print what came back.

Each question runs in a fresh session. Prints the answer text, any error event,
the ACTION hints, and the wall time. Counts against the copilot's daily budget
(one request per question), so keep lists short.

    python3 apps/api/scripts/copilot_probe.py "How many monitors are in KPK?" "Nearest station to Mardan?"
    python3 apps/api/scripts/copilot_probe.py --file questions.txt --date 2026-11-03
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import uuid

DEFAULT_URL = "https://hawanama-152782825429.asia-south1.run.app/api/v1/ops/analyst-desk/copilot/chat"
ORIGIN = "https://hawanama.org"


def ask(url: str, question: str, date: str = "", timeout: float = 180.0) -> dict:
    body = {"session_id": "probe-" + uuid.uuid4().hex[:12], "message": question,
            "context": {"location": {"type": "national"}}}
    if date:
        body["date"] = date
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Origin": ORIGIN})
    t0 = time.time()
    text, errors, actions = [], [], []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            kind = ev.get("type")
            if kind == "text":
                text.append(ev.get("content", ""))
            elif kind == "error":
                errors.append(ev.get("content", ""))
            elif kind == "action":
                actions.append(ev.get("action"))
    return {"question": question, "answer": "".join(text).strip(), "errors": errors, "actions": actions,
            "seconds": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("questions", nargs="*")
    ap.add_argument("--file", help="one question per line")
    ap.add_argument("--date", default="", help="dashboard forecast date to send (YYYY-MM-DD)")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--json", action="store_true", help="print one JSON object per question")
    args = ap.parse_args()
    questions = list(args.questions)
    if args.file:
        questions += [q.strip() for q in open(args.file, encoding="utf-8") if q.strip() and not q.startswith("#")]
    if not questions:
        ap.error("no questions given")
    failures = 0
    for q in questions:
        try:
            res = ask(args.url, q, args.date)
        except Exception as exc:  # noqa: BLE001 — report and continue with the next question
            res = {"question": q, "answer": "", "errors": [f"{type(exc).__name__}: {exc}"], "actions": [], "seconds": None}
        if res["errors"] or not res["answer"]:
            failures += 1
        if args.json:
            print(json.dumps(res, ensure_ascii=False))
        else:
            print(f"\n### {q}  [{res['seconds']}s]\n{res['answer'] or '(empty reply)'}")
            if res["errors"]:
                print(f"ERRORS: {res['errors']}")
            if res["actions"]:
                print(f"ACTIONS: {res['actions']}")
    print(f"\n{len(questions) - failures}/{len(questions)} answered without error", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
