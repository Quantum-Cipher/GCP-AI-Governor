# Copyright (c) 2026 Drake Daniel Peters
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)

import json
import pytest
from daemon.main import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["service"] == "gcp-ai-governor"
    assert "live_mode" in data


def test_event_owner_revoke(client):
    event = {
        "event_type": "iam.roleGranted",
        "principal": "test-user",
        "resource": "projects/test",
        "roleGranted": "roles/owner",
    }
    resp = client.post("/event", data=json.dumps(event), content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["decision"] == "revoke"


def test_event_viewer_allow(client):
    event = {
        "event_type": "iam.roleGranted",
        "principal": "test-user",
        "resource": "projects/test",
        "roleGranted": "roles/viewer",
    }
    resp = client.post("/event", data=json.dumps(event), content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["decision"] == "allow"


def test_event_heartbeat_ignore(client):
    event = {
        "event_type": "heartbeat",
        "principal": "system-agent",
        "resource": "projects/test",
        "roleGranted": "",
    }
    resp = client.post("/event", data=json.dumps(event), content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["decision"] == "ignore"


def test_root_event_with_proto_payload(client):
    payload = {
        "protoPayload": {
            "methodName": "iam.roleGranted",
            "authenticationInfo": {"principalEmail": "admin@example.com"},
            "resourceName": "projects/test",
            "roleGranted": "roles/owner",
        }
    }
    resp = client.post("/", data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["decision"] == "revoke"


def test_root_event_empty_payload(client):
    resp = client.post("/", data=json.dumps({}), content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["decision"] == "allow"


def test_max_content_length():
    assert app.config["MAX_CONTENT_LENGTH"] == 1 * 1024 * 1024
