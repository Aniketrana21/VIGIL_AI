"""
VIGIL-AI: Interactive Database Management Tool (CLI & Scriptable).
Allows manual CRUD operations (Create/Enter, Read, Update, Delete) on detection_events.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure backend path is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.db.detection_store import DetectionEvent, get_detection_store


def get_store():
    return get_detection_store()


def cmd_list(args):
    store = get_store()
    limit = args.limit or 20
    events = store.get_detections_sync(limit=limit)

    if args.level:
        events = [e for e in events if e.risk_level == args.level.upper()]
    if args.action:
        events = [e for e in events if e.action == args.action.upper()]

    print("=" * 85)
    print(f"📋 VIGIL-AI DETECTION AUDIT RECORDS (Showing {len(events)} records)")
    print("=" * 85)
    if not events:
        print("No matching records found in database.")
        return

    print(f"{'ID':<5} | {'TIMESTAMP (UTC)':<19} | {'RISK':<5} | {'LEVEL':<8} | {'ACTION':<9} | {'DEEPFAKE':<8} | {'SESSION ID':<30}")
    print("-" * 85)
    for e in events:
        df = f"{e.deepfake_score:.2f}" if e.deepfake_score is not None else "N/A"
        print(f"{e.id:<5} | {str(e.timestamp)[:19]:<19} | {e.risk_score:<5} | {e.risk_level:<8} | {e.action:<9} | {df:<8} | {e.session_id[:30]:<30}")
    print("=" * 85)


def cmd_get(args):
    store = get_store()
    event = store.get_detection_by_id_sync(args.id)
    if not event:
        print(f"❌ Record ID #{args.id} not found.")
        return

    print("=" * 70)
    print(f"🔍 DETECTION RECORD DETAILS: ID #{event.id}")
    print("=" * 70)
    print(f"• Session ID            : {event.session_id}")
    print(f"• Timestamp             : {event.timestamp}")
    print(f"• Spoken Text           : \"{event.transcript or 'None'}\"")
    print(f"• Deepfake Score        : {event.deepfake_score} (Label: {event.deepfake_label})")
    print(f"• Speaker ID            : {event.speaker_id or 'UNKNOWN'}")
    print(f"• Speaker Similarity    : {event.speaker_similarity}")
    print(f"• Acoustic Liveness     : {event.liveness_score}")
    print(f"• Replay Probability    : {event.replay_probability}")
    print(f"• Conversation Intent   : {event.conversation_intent}")
    print(f"• Conversation Risk     : {event.conversation_risk}")
    print(f"• Composite Risk Score  : {event.risk_score} / 100")
    print(f"• Threat Risk Level     : {event.risk_level}")
    print(f"• Automated Action      : {event.action}")
    print(f"• Model Confidence      : {event.confidence}")
    print(f"• Active Flags          : {event.signals}")
    print(f"• Caller Metadata       : {event.caller_id}")
    print(f"• Full Explanation      :\n  {event.explanation}")
    print("=" * 70)


def cmd_add(args):
    store = get_store()
    session_id = args.session or f"manual-{int(os.times().system * 1000)}"
    risk_score = args.risk if args.risk is not None else 50
    risk_level = args.level.upper() if args.level else ("CRITICAL" if risk_score >= 85 else "HIGH" if risk_score >= 60 else "MEDIUM" if risk_score >= 35 else "LOW")
    action = args.action.upper() if args.action else ("BLOCK" if risk_level == "CRITICAL" else "CHALLENGE" if risk_level in ("HIGH", "MEDIUM") else "ALLOW")

    event = DetectionEvent(
        session_id=session_id,
        transcript=getattr(args, "transcript", None),
        risk_score=risk_score,
        risk_level=risk_level,
        action=action,
        deepfake_score=args.deepfake,
        deepfake_label="spoof" if (args.deepfake and args.deepfake >= 0.5) else "bonafide",
        speaker_id=args.speaker,
        speaker_similarity=args.similarity,
        liveness_score=args.liveness,
        replay_probability=args.replay,
        conversation_intent=args.intent or "INFORMATIONAL",
        conversation_risk=args.conv_risk,
        confidence=args.confidence if args.confidence is not None else 0.90,
        signals=[s.strip() for s in args.signals.split(",")] if args.signals else ["MANUALLY_ENTERED_RECORD"],
        explanation=args.explanation or f"Manually entered detection record via manage_db.py. Verdict: {action}.",
        caller_id=args.caller or "+91-MANUAL-ENTRY",
        metadata={"created_via": "manage_db.py", "manual": True},
    )

    success = store.store_detection_sync(event)
    if success:
        print(f"✅ Record created successfully! New Record ID: #{event.id} (Session: {event.session_id})")
    else:
        print("❌ Failed to enter record into database.")


def cmd_update(args):
    store = get_store()
    event = store.get_detection_by_id_sync(args.id)
    if not event:
        print(f"❌ Record ID #{args.id} not found.")
        return

    updates: Dict[str, Any] = {}
    if args.risk is not None:
        updates["risk_score"] = args.risk
    if args.level:
        updates["risk_level"] = args.level.upper()
    if args.action:
        updates["action"] = args.action.upper()
    if args.deepfake is not None:
        updates["deepfake_score"] = args.deepfake
    if args.label:
        updates["deepfake_label"] = args.label
    if args.explanation:
        updates["explanation"] = args.explanation
    if getattr(args, "transcript", None):
        updates["transcript"] = args.transcript
    if args.caller:
        updates["caller_id"] = args.caller

    if not updates:
        print("⚠️ No update fields provided. Specify --risk, --level, --action, or --explanation.")
        return

    success = store.update_detection_sync(args.id, updates)
    if success:
        print(f"✅ Record ID #{args.id} updated successfully: {updates}")
    else:
        print(f"❌ Failed to update Record ID #{args.id}.")


def cmd_delete(args):
    store = get_store()
    event = store.get_detection_by_id_sync(args.id)
    if not event:
        print(f"❌ Record ID #{args.id} does not exist.")
        return

    success = store.delete_detection_sync(args.id)
    if success:
        print(f"🗑️ Record ID #{args.id} deleted successfully.")
    else:
        print(f"❌ Failed to delete Record ID #{args.id}.")


def cmd_clear(args):
    if not args.force:
        confirm = input("⚠️ Are you sure you want to delete ALL records from database? (yes/no): ").strip().lower()
        if confirm not in ("yes", "y"):
            print("Operation aborted.")
            return

    store = get_store()
    count = store.clear_detections_sync()
    print(f"🧹 Database cleared. Deleted {count} records.")


def cmd_interactive(args):
    print("=" * 60)
    print(" 🛠️  VIGIL-AI INTERACTIVE DATABASE MANAGER")
    print("=" * 60)
    store = get_store()

    while True:
        print("\nOptions:")
        print("  1) List recent records")
        print("  2) View specific record by ID")
        print("  3) Enter a new record manually")
        print("  4) Update an existing record")
        print("  5) Delete a record by ID")
        print("  6) Exit")
        choice = input("\nSelect an option (1-6): ").strip()

        if choice == "1":
            limit = input("Limit [default 10]: ").strip()
            args.limit = int(limit) if limit.isdigit() else 10
            args.level = None
            args.action = None
            cmd_list(args)
        elif choice == "2":
            r_id = input("Enter Record ID to view: ").strip()
            if r_id.isdigit():
                args.id = int(r_id)
                cmd_get(args)
        elif choice == "3":
            print("\n--- Enter New Record ---")
            sess = input("Session ID [e.g. manual-test-01]: ").strip() or "manual-test"
            risk_raw = input("Risk Score (0-100) [default 50]: ").strip()
            risk = int(risk_raw) if risk_raw.isdigit() else 50
            level = input("Risk Level (LOW / MEDIUM / HIGH / CRITICAL) [auto]: ").strip().upper()
            action = input("Action (ALLOW / CHALLENGE / WARN / BLOCK) [auto]: ").strip().upper()
            df_raw = input("Deepfake Probability (0.0 to 1.0) [e.g. 0.85]: ").strip()
            df = float(df_raw) if df_raw else None
            expl = input("Explanation note: ").strip() or "Manual entry"

            args.session = sess
            args.risk = risk
            args.level = level if level else None
            args.action = action if action else None
            args.deepfake = df
            args.speaker = None
            args.similarity = None
            args.liveness = None
            args.replay = None
            args.intent = None
            args.conv_risk = None
            args.confidence = 0.90
            args.signals = "MANUAL_ENTRY"
            args.explanation = expl
            args.caller = "+91-TEST"
            cmd_add(args)
        elif choice == "4":
            r_id = input("Enter Record ID to update: ").strip()
            if not r_id.isdigit():
                continue
            args.id = int(r_id)
            print(f"Updating Record #{args.id} (press enter to leave unchanged):")
            risk_raw = input("New Risk Score (0-100): ").strip()
            args.risk = int(risk_raw) if risk_raw.isdigit() else None
            level = input("New Risk Level (LOW / MEDIUM / HIGH / CRITICAL): ").strip().upper()
            args.level = level if level else None
            action = input("New Action (ALLOW / CHALLENGE / WARN / BLOCK): ").strip().upper()
            args.action = action if action else None
            expl = input("New Explanation note: ").strip()
            args.explanation = expl if expl else None
            args.deepfake = None
            args.label = None
            args.caller = None
            cmd_update(args)
        elif choice == "5":
            r_id = input("Enter Record ID to delete: ").strip()
            if r_id.isdigit():
                args.id = int(r_id)
                cmd_delete(args)
        elif choice in ("6", "q", "exit"):
            print("Goodbye!")
            break


def main():
    parser = argparse.ArgumentParser(description="VIGIL-AI Database Management Tool")
    subparsers = parser.add_subparsers(dest="subcommand", help="Command to execute")

    # list
    p_list = subparsers.add_parser("list", help="List records in database")
    p_list.add_argument("--limit", "-n", type=int, default=15, help="Number of records to show")
    p_list.add_argument("--level", "-l", type=str, choices=["LOW", "MEDIUM", "HIGH", "CRITICAL"], help="Filter by risk level")
    p_list.add_argument("--action", "-a", type=str, choices=["ALLOW", "MONITOR", "CHALLENGE", "WARN", "BLOCK"], help="Filter by action")
    p_list.set_defaults(func=cmd_list)

    # get
    p_get = subparsers.add_parser("get", help="Get a single record by ID")
    p_get.add_argument("id", type=int, help="Record ID")
    p_get.set_defaults(func=cmd_get)

    # add
    p_add = subparsers.add_parser("add", help="Enter a new detection record")
    p_add.add_argument("--session", "-s", type=str, help="Session ID")
    p_add.add_argument("--risk", "-r", type=int, default=50, help="Risk score (0-100)")
    p_add.add_argument("--level", "-l", type=str, choices=["LOW", "MEDIUM", "HIGH", "CRITICAL"], help="Risk level")
    p_add.add_argument("--action", "-a", type=str, choices=["ALLOW", "MONITOR", "CHALLENGE", "WARN", "BLOCK"], help="Action")
    p_add.add_argument("--deepfake", "-d", type=float, help="Deepfake score (0.0 - 1.0)")
    p_add.add_argument("--speaker", type=str, help="Speaker ID")
    p_add.add_argument("--similarity", type=float, help="Speaker similarity")
    p_add.add_argument("--liveness", type=float, help="Liveness score")
    p_add.add_argument("--replay", type=float, help="Replay probability")
    p_add.add_argument("--intent", type=str, help="Conversation intent")
    p_add.add_argument("--conv-risk", type=float, help="Conversation risk")
    p_add.add_argument("--confidence", type=float, default=0.90, help="Confidence")
    p_add.add_argument("--signals", type=str, help="Comma-separated threat flags")
    p_add.add_argument("--transcript", "-t", type=str, help="Spoken text or transcript")
    p_add.add_argument("--explanation", "-e", type=str, help="Explanation note")
    p_add.add_argument("--caller", type=str, help="Caller ID")
    p_add.set_defaults(func=cmd_add)

    # update
    p_upd = subparsers.add_parser("update", help="Update an existing detection record")
    p_upd.add_argument("id", type=int, help="Record ID to update")
    p_upd.add_argument("--risk", "-r", type=int, help="New risk score")
    p_upd.add_argument("--level", "-l", type=str, choices=["LOW", "MEDIUM", "HIGH", "CRITICAL"], help="New risk level")
    p_upd.add_argument("--action", "-a", type=str, choices=["ALLOW", "MONITOR", "CHALLENGE", "WARN", "BLOCK"], help="New action")
    p_upd.add_argument("--deepfake", "-d", type=float, help="New deepfake score")
    p_upd.add_argument("--label", type=str, help="New deepfake label")
    p_upd.add_argument("--transcript", "-t", type=str, help="New spoken text / transcript")
    p_upd.add_argument("--explanation", "-e", type=str, help="New explanation")
    p_upd.add_argument("--caller", type=str, help="New caller ID")
    p_upd.set_defaults(func=cmd_update)

    # delete
    p_del = subparsers.add_parser("delete", help="Delete a detection record by ID")
    p_del.add_argument("id", type=int, help="Record ID to delete")
    p_del.set_defaults(func=cmd_delete)

    # clear
    p_clr = subparsers.add_parser("clear", help="Clear all records from database")
    p_clr.add_argument("--force", "-f", action="store_true", help="Force deletion without prompt")
    p_clr.set_defaults(func=cmd_clear)

    # interactive
    p_itr = subparsers.add_parser("interactive", help="Interactive menu wizard")
    p_itr.set_defaults(func=cmd_interactive)

    args = parser.parse_args()
    if not args.subcommand:
        # Default to interactive wizard if no args provided
        cmd_interactive(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
