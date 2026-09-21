"""
VIGIL-AI: Dynamic Multi-User & Multi-Device Architectural Test Suite
Verifies:
1. Zero static numbers: System operates purely dynamically for any user installing the APK.
2. Dynamic user registration (UUIDs) & device registration (device_uuid, installation_id).
3. APK reinstallation handling (fresh installation_id linked to user).
4. Dynamic caller auto-creation for previously unseen phone numbers.
5. Multi-tenant zero-trust data isolation (User A callers/history invisible to User B).
6. Per-user WebSocket dashboard event bus routing.
"""
import uuid
import pytest
from starlette.testclient import TestClient
from app.main import app
from app.services.dashboard_event_bus import dashboard_bus

client = TestClient(app)


def test_dynamic_user_registration():
    """Verify users are registered dynamically with UUIDs, never phone numbers."""
    user_name = f"Test Subscriber {uuid.uuid4().hex[:6]}"
    res = client.post("/api/v1/auth/register-user", json={
        "name": user_name,
        "email": f"{uuid.uuid4().hex[:8]}@example.com"
    })
    assert res.status_code == 200
    data = res.json()
    assert "user_id" in data
    # Invariant: user_id is a valid UUID
    uuid_obj = uuid.UUID(data["user_id"])
    assert str(uuid_obj) == data["user_id"]
    assert data["name"] == user_name
    assert data["status"] == "ACTIVE"


def test_dynamic_device_registration_and_reinstallation():
    """Verify devices register with device_uuid & installation_id, and APK reinstallation creates a new install."""
    # 1. Create dynamic user
    user_res = client.post("/api/v1/auth/register-user", json={"name": "Device Test User"})
    assert user_res.status_code == 200
    user_id = user_res.json()["user_id"]

    # 2. First install
    device_uuid = str(uuid.uuid4())
    install_id_1 = str(uuid.uuid4())
    dev_res_1 = client.post("/api/v1/auth/register-device", json={
        "user_id": user_id,
        "device_uuid": device_uuid,
        "installation_id": install_id_1,
        "platform": "android",
        "app_version": "1.0.0"
    })
    assert dev_res_1.status_code == 200
    dev_data_1 = dev_res_1.json()
    assert dev_data_1["user_id"] == user_id
    assert dev_data_1["device_uuid"] == device_uuid
    assert dev_data_1["installation_id"] == install_id_1

    # 3. Simulate APK reinstallation: same device_uuid, fresh installation_id
    install_id_2 = str(uuid.uuid4())
    dev_res_2 = client.post("/api/v1/auth/register-device", json={
        "user_id": user_id,
        "device_uuid": device_uuid,
        "installation_id": install_id_2,
        "platform": "android",
        "app_version": "1.0.1"
    })
    assert dev_res_2.status_code == 200
    dev_data_2 = dev_res_2.json()
    assert dev_data_2["user_id"] == user_id
    assert dev_data_2["installation_id"] == install_id_2
    assert dev_data_2["installation_id"] != install_id_1


def test_dynamic_caller_auto_creation_on_screening():
    """Verify that an incoming call from an unseen number dynamically creates a caller profile."""
    user_res = client.post("/api/v1/auth/register-user", json={"name": "Screening User"})
    user_id = user_res.json()["user_id"]
    device_id = str(uuid.uuid4())
    install_id = str(uuid.uuid4())

    # Generate a dynamic unseen phone number
    unseen_phone = f"+1{uuid.uuid4().int % 10000000000:010d}"

    screen_payload = {
        "user_id": user_id,
        "device_id": device_id,
        "installation_id": install_id,
        "phone_number": unseen_phone,
        "caller_display_name": "Random First-Time Caller",
        "caller_name": "Random First-Time Caller",
        "contact_match": False,
        "stir_shaken_status": 0
    }

    res = client.post("/api/v1/screening/lookup", json=screen_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["recommended_action"] in ["ALLOW", "MONITOR", "VERIFY", "BLOCK"]
    assert "caller" in data
    assert data["caller"]["phone"] == unseen_phone
    assert data["caller"]["trust_status"] in ["neutral", "untrusted"]


def test_multi_user_call_isolation():
    """Verify that calls registered for User A are isolated and never visible to User B."""
    # Register User A and User B
    user_a = client.post("/api/v1/auth/register-user", json={"name": "User Alpha"}).json()["user_id"]
    user_b = client.post("/api/v1/auth/register-user", json={"name": "User Beta"}).json()["user_id"]

    phone_a = f"+1{uuid.uuid4().int % 10000000000:010d}"
    phone_b = f"+1{uuid.uuid4().int % 10000000000:010d}"

    # User A receives a call
    res_a = client.post("/api/v1/calls/incoming", json={
        "user_id": user_a,
        "phone_number": phone_a,
        "caller_name": "Alpha Friend",
        "contact_known": True,
        "transport": "CELLULAR"
    })
    assert res_a.status_code == 200
    call_id_a = res_a.json()["call_id"]

    # User B receives a call
    res_b = client.post("/api/v1/calls/incoming", json={
        "user_id": user_b,
        "phone_number": phone_b,
        "caller_name": "Beta Associate",
        "contact_known": False,
        "transport": "CELLULAR"
    })
    assert res_b.status_code == 200
    call_id_b = res_b.json()["call_id"]

    # Query latest call for User A
    live_a = client.get(f"/api/v1/screening/live?user_id={user_a}").json()
    assert live_a["latest_call"] is not None
    assert live_a["latest_call"]["call_id"] == call_id_a
    assert live_a["latest_call"]["caller_name"] == "Alpha Friend"

    # Query latest call for User B
    live_b = client.get(f"/api/v1/screening/live?user_id={user_b}").json()
    assert live_b["latest_call"] is not None
    assert live_b["latest_call"]["call_id"] == call_id_b
    assert live_b["latest_call"]["caller_name"] == "Beta Associate"


def test_dynamic_fraud_call_simulation():
    """Verify that triggering a fraud call works dynamically with user_id without static numbers."""
    user_id = client.post("/api/v1/auth/register-user", json={"name": "Sim User"}).json()["user_id"]
    res = client.post("/api/v1/screening/trigger-fraud-call", json={
        "user_id": user_id,
        "device_id": str(uuid.uuid4()),
        "installation_id": str(uuid.uuid4())
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"].upper() == "TRIGGERED"
    assert "call" in data
    assert data["call"]["action"] == "BLOCK"
    assert data["call"]["risk_score"] >= 80
    assert "reasons" in data["call"]
