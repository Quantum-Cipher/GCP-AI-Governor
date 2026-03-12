# Copyright (c) 2026 Drake Daniel Peters
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)

from daemon.policies.policy_engine import evaluate_event


def test_owner_role_revoked():
    event = {"roleGranted": "roles/owner", "event_type": "iam.roleGranted"}
    assert evaluate_event(event) == "revoke"


def test_editor_role_revoked():
    event = {"roleGranted": "roles/editor", "event_type": "iam.roleGranted"}
    assert evaluate_event(event) == "revoke"


def test_service_account_admin_revoked():
    event = {"roleGranted": "roles/iam.serviceAccountAdmin", "event_type": "iam.roleGranted"}
    assert evaluate_event(event) == "revoke"


def test_project_iam_admin_revoked():
    event = {"roleGranted": "roles/resourcemanager.projectIamAdmin", "event_type": "iam.roleGranted"}
    assert evaluate_event(event) == "revoke"


def test_viewer_role_allowed():
    event = {"roleGranted": "roles/viewer", "event_type": "iam.roleGranted"}
    assert evaluate_event(event) == "allow"


def test_browser_role_allowed():
    event = {"roleGranted": "roles/browser", "event_type": "iam.roleGranted"}
    assert evaluate_event(event) == "allow"


def test_heartbeat_ignored():
    event = {"roleGranted": "", "event_type": "heartbeat"}
    assert evaluate_event(event) == "ignore"


def test_healthcheck_ignored():
    event = {"roleGranted": "", "event_type": "healthcheck"}
    assert evaluate_event(event) == "ignore"


def test_noop_ignored():
    event = {"roleGranted": "", "event_type": "noop"}
    assert evaluate_event(event) == "ignore"


def test_unknown_event_allowed():
    event = {"roleGranted": "", "event_type": "unknown"}
    assert evaluate_event(event) == "allow"


def test_empty_event_allowed():
    event = {}
    assert evaluate_event(event) == "allow"
