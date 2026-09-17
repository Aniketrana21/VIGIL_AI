import sqlite3
import json
import sys
from pathlib import Path

# Configure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

db_candidates = [
    Path("backend/vigil_detections.db"),
    Path("vigil_detections.db"),
]

db_path = None
for p in db_candidates:
    if p.exists():
        db_path = p
        break

if not db_path:
    print("❌ No database file found!")
    sys.exit(1)

print("=" * 80)
print(f"📊 DATABASE ENGINE: SQLite (Production-upgradeable to PostgreSQL)")
print(f"📁 Database File   : {db_path.resolve()}")
print(f"📋 Table Name      : detection_events")
print("=" * 80)

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. Overall Stats
cur.execute("SELECT COUNT(*) as total FROM detection_events")
total_count = cur.fetchone()["total"]

cur.execute("SELECT action, COUNT(*) as cnt FROM detection_events GROUP BY action")
action_counts = {row["action"]: row["cnt"] for row in cur.fetchall()}

cur.execute("SELECT risk_level, COUNT(*) as cnt FROM detection_events GROUP BY risk_level")
level_counts = {row["risk_level"]: row["cnt"] for row in cur.fetchall()}

print(f"\n📈 Summary Metrics:")
print(f"   • Total Detections Logged : {total_count}")
print(f"   • Actions Breakdown       : {action_counts}")
print(f"   • Risk Level Breakdown    : {level_counts}")
print("\n" + "=" * 80)
print("🔍 RECENT VOICE DETECTION AUDIT RECORDS (Latest First):")
print("=" * 80)

cur.execute("""
    SELECT id, session_id, timestamp, deepfake_score, deepfake_label, 
           speaker_id, speaker_similarity, liveness_score, replay_probability,
           conversation_intent, conversation_risk,
           risk_score, risk_level, action, confidence, signals, explanation
    FROM detection_events
    ORDER BY id DESC
    LIMIT 6
""")
rows = cur.fetchall()

for row in rows:
    r_id = row["id"]
    sess = row["session_id"]
    ts = str(row["timestamp"])[:19]
    df_sc = f"{row['deepfake_score']:.3f}" if row["deepfake_score"] is not None else "N/A"
    df_lbl = row["deepfake_label"] or "N/A"
    spk = row["speaker_id"] or "Unknown"
    spk_sim = f"{row['speaker_similarity']:.2f}" if row["speaker_similarity"] is not None else "N/A"
    live = f"{row['liveness_score']:.2f}" if row["liveness_score"] is not None else "N/A"
    replay = f"{row['replay_probability']:.2f}" if row["replay_probability"] is not None else "N/A"
    intent = row["conversation_intent"] or "INFORMATIONAL"
    r_score = row["risk_score"]
    r_level = row["risk_level"]
    act = row["action"]
    conf = f"{row['confidence']:.2f}" if row["confidence"] is not None else "1.00"
    
    signals = json.loads(row["signals"]) if row["signals"] else []
    expl = (row["explanation"] or "").strip().replace("\n", " ")
    if len(expl) > 90:
        expl = expl[:87] + "..."

    print(f"\n🏷️  Record ID #{r_id:03d} | 🕒 Timestamp: {ts} UTC | 🔑 Session: {sess}")
    print(f"   ├─ Deepfake Detection   : Score={df_sc} | Label={df_lbl} | Model=WavLM-AASIST-v1.0")
    print(f"   ├─ Speaker Verification : ID={spk} | Similarity={spk_sim} | Model=ECAPA-TDNN-v1.0")
    print(f"   ├─ Acoustic Liveness    : Liveness={live} | Replay Probability={replay}")
    print(f"   ├─ Context Threat (NLP) : Intent={intent} | Conversation Risk={row['conversation_risk']}")
    print(f"   ├─ Multi-Factor Verdict : RISK={r_score}/100 [{r_level}] ➔ ACTION: [{act}] (Conf: {conf})")
    print(f"   ├─ Active Flags         : {signals if signals else ['NOMINAL']}")
    print(f"   └─ Explainability Log   : {expl}")

print("\n" + "=" * 80)
conn.close()
