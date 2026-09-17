import pytest
from app.pipeline.session_manager import StreamingSessionManager
from app.pipeline.validator import AudioChunkValidator


def test_invalid_pcm_rejection():
    validator = AudioChunkValidator(expected_sample_rate=16000)

    # 1. Truncated binary header (< 28 bytes)
    res_trunc = validator.validate_raw(b"VIGI_short")
    assert not res_trunc.is_valid
    assert "smaller than header size" in res_trunc.error_message or "not aligned" in res_trunc.error_message

    # 2. Corrupt magic header (28 bytes with bad magic)
    bad_magic = b"XXXX" + b"\x00" * 24
    res_magic = validator.validate_raw(bad_magic)
    assert not res_magic.is_valid

    # 3. Odd number of PCM bytes (violates 16-bit alignment)
    odd_pcm = b"\x01\x02\x03"
    res_odd = validator.validate_raw(odd_pcm)
    assert not res_odd.is_valid
    assert "not aligned" in res_odd.error_message

    # 4. Malformed JSON string
    res_json = validator.validate_raw("{invalid_json_payload")
    assert not res_json.is_valid
    assert "parse failure" in res_json.error_message

    # 5. Invalid JSON structure missing fields
    res_missing = validator.validate_raw({"foo": "bar"})
    assert not res_missing.is_valid


def test_backend_never_crashes_on_hostile_input():
    session = StreamingSessionManager(session_id="crash_test_session")

    hostile_inputs = [
        b"",
        b"\x00",
        b"\xff" * 1000,
        "null",
        "",
        {"type": "AUDIO_CHUNK", "sequence_id": "not_an_int", "pcm_base64": "???"},
        b"VIGI" + b"\xff" * 100,
    ]

    for bad_input in hostile_inputs:
        windows, telem = session.ingest_packet(bad_input)
        # Verify no unhandled exception occurred and error is recorded
        assert isinstance(windows, list)
        assert isinstance(telem, dict)
        assert telem["connection_state"] == "CONNECTED"

    session.close()
