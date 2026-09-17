import requests
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


base_url = "http://127.0.0.1:8000"

# 1. Health check
res = requests.get(f"{base_url}/health")
print("Health status:", res.status_code, res.json())
assert res.status_code == 200

# 2. Readiness check
res_ready = requests.get(f"{base_url}/ready")
print("Readiness status:", res_ready.status_code, res_ready.json())
assert res_ready.status_code == 200

# 3. Get scenarios
resp = requests.get(f"{base_url}/api/v1/demo/scenarios").json()
scenarios = resp["scenarios"]
print(f"Scenarios count: {len(scenarios)}")
assert len(scenarios) == 5
assert resp["demo_mode"] is True


# 4. Test all 5 scenarios sequentially via POST /api/v1/demo/run
for sc in scenarios:
    sc_id = sc["id"]
    run_res = requests.post(f"{base_url}/api/v1/demo/run", json={"scenario_id": sc_id})
    assert run_res.status_code == 200, f"Failed on {sc_id}: {run_res.text}"
    data = run_res.json()
    metrics = data["metrics"]
    level = metrics["risk_level"]
    action = metrics["action"]
    score = metrics["risk_score"]
    explanation = data["explanation"]
    print(f"  [{sc_id}: {sc['title']}] -> Level: {level}, Action: {action}, Score: {score}/100")
    print(f"       Explanation: {explanation[:70]}...")


# 5. Verify detection events in DB
from app.db.detection_store import get_detection_store
store = get_detection_store()
events = store.get_detections_sync(limit=10)
print(f"Total verified events stored in DB: {len(events)}")
assert len(events) >= 5
for ev in events[:5]:
    print(f"   [DB Event #{ev.id}] Session: {ev.session_id} | Risk: {ev.risk_score} | Action: {ev.action} | Deepfake: {ev.deepfake_score}")

# 6. Verify real-time WebSocket streaming
import asyncio
import websockets

async def verify_ws():
    uri = "ws://127.0.0.1:8000/api/v1/demo/stream/4"
    async with websockets.connect(uri) as ws:
        received_chunks = 0
        last_chunk = None
        while True:
            msg = await ws.recv()
            evt = json.loads(msg)
            msg_type = evt.get("type")
            if msg_type == "DEMO_CHUNK":
                received_chunks += 1
                last_chunk = evt
            elif msg_type == "DEMO_COMPLETE":
                print(f"[WebSocket] Scenario {evt.get('scenario_id')} complete: {evt.get('message')}")
                break

        print(f"[WebSocket] Streaming complete! Chunks received: {received_chunks}")
        assert received_chunks > 0
        metrics = last_chunk.get("metrics", {})
        level = metrics.get("risk_level")
        action = metrics.get("action")
        score = metrics.get("risk_score")
        print(f"[WebSocket] Final Frame Verdict -> Level: {level}, Action: {action}, Score: {score}/100")
        assert action == "BLOCK"
        assert level == "CRITICAL"

asyncio.run(verify_ws())

print("\nSUCCESS: All REST, WebSocket, ML Pipelines, and DB Stores verified with ZERO runtime errors!")



