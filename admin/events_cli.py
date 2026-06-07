#!/usr/bin/env python3
"""Events admin CLI — approve or reject community event submissions.

Usage:
  python admin/events_cli.py list
  python admin/events_cli.py review
  python admin/events_cli.py submit --title "..." --date 2025-07-04 --desc "..." [--url ...]
  python admin/events_cli.py approve <id>
  python admin/events_cli.py reject <id>
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SUBMISSIONS = Path("data/events/submissions")
APPROVED = Path("data/events/approved")
REJECTED = Path("data/events/rejected")

for d in (SUBMISSIONS, APPROVED, REJECTED):
    d.mkdir(parents=True, exist_ok=True)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_event(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_event(path: Path, event: dict) -> None:
    path.write_text(json.dumps(event, indent=2), encoding="utf-8")


def cmd_submit(args):
    uid = hashlib.md5(f"{args.title}{args.date}".encode()).hexdigest()[:12]
    event = {
        "id": uid,
        "title": args.title,
        "date": args.date,
        "description": args.desc,
        "url": args.url or "",
        "submitted_at": now_iso(),
        "status": "pending",
    }
    path = SUBMISSIONS / f"{uid}.json"
    save_event(path, event)
    print(f"Submitted: {uid}")
    print(f"  {args.title} on {args.date}")


def cmd_list(args):
    pending = sorted(SUBMISSIONS.glob("*.json"))
    if not pending:
        print("No pending submissions.")
        return
    print(f"{'ID':<14} {'Date':<12} Title")
    print("-" * 60)
    for p in pending:
        e = load_event(p)
        print(f"{e['id']:<14} {e['date']:<12} {e['title']}")


def cmd_review(args):
    pending = sorted(SUBMISSIONS.glob("*.json"))
    if not pending:
        print("No pending submissions.")
        return
    for p in pending:
        e = load_event(p)
        print(f"\n{'─'*60}")
        print(f"ID:    {e['id']}")
        print(f"Title: {e['title']}")
        print(f"Date:  {e['date']}")
        print(f"Desc:  {e['description']}")
        if e.get("url"):
            print(f"URL:   {e['url']}")
        choice = input("Approve [a], Reject [r], Skip [s]? ").strip().lower()
        if choice == "a":
            _approve(e, p)
        elif choice == "r":
            _reject(e, p)
        else:
            print("Skipped.")


def _approve(event: dict, src: Path) -> None:
    event["status"] = "approved"
    event["approved_at"] = now_iso()
    dest = APPROVED / src.name
    save_event(dest, event)
    src.unlink()
    print(f"✓ Approved: {event['title']}")


def _reject(event: dict, src: Path) -> None:
    event["status"] = "rejected"
    event["rejected_at"] = now_iso()
    dest = REJECTED / src.name
    save_event(dest, event)
    src.unlink()
    print(f"✗ Rejected: {event['title']}")


def cmd_approve(args):
    matches = list(SUBMISSIONS.glob(f"{args.id}*.json"))
    if not matches:
        print(f"No submission found with id {args.id}")
        sys.exit(1)
    e = load_event(matches[0])
    _approve(e, matches[0])


def cmd_reject(args):
    matches = list(SUBMISSIONS.glob(f"{args.id}*.json"))
    if not matches:
        print(f"No submission found with id {args.id}")
        sys.exit(1)
    e = load_event(matches[0])
    _reject(e, matches[0])


def main():
    parser = argparse.ArgumentParser(description="Oxted Bugle Events Admin")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List pending submissions")
    sub.add_parser("review", help="Interactively review submissions")

    p_submit = sub.add_parser("submit", help="Submit a community event")
    p_submit.add_argument("--title", required=True)
    p_submit.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_submit.add_argument("--desc", required=True)
    p_submit.add_argument("--url", default="")

    p_approve = sub.add_parser("approve", help="Approve a submission by ID")
    p_approve.add_argument("id")

    p_reject = sub.add_parser("reject", help="Reject a submission by ID")
    p_reject.add_argument("id")

    args = parser.parse_args()
    commands = {
        "list": cmd_list, "review": cmd_review,
        "submit": cmd_submit, "approve": cmd_approve, "reject": cmd_reject,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
