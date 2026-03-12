# Copyright (c) 2026 Drake Daniel Peters
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
#
# This file is part of the GCP AI Governor project.
# See the LICENSE file for full license text.

import json

import requests

URL = "http://127.0.0.1:8080/event"

test_events = [
    {
        "event_type": "iam.roleGranted",
        "principal": "test-owner-user",
        "resource": "projects/mythosblock-core",
        "roleGranted": "roles/owner"
    },
    {
        "event_type": "iam.roleGranted",
        "principal": "test-viewer-user",
        "resource": "projects/mythosblock-core",
        "roleGranted": "roles/viewer"
    },
    {
        "event_type": "iam.roleGranted",
        "principal": "test-admin-user",
        "resource": "projects/mythosblock-core",
        "roleGranted": "roles/iam.serviceAccountAdmin"
    },
    {
        "event_type": "heartbeat",
        "principal": "system-agent",
        "resource": "projects/mythosblock-core",
        "roleGranted": ""
    }
]

for idx, event in enumerate(test_events, start=1):
    print(f"\n=== Sending test event {idx} ===")
    print(json.dumps(event, indent=2))

    response = requests.post(URL, json=event, timeout=10)

    print("Response:")
    print(json.dumps(response.json(), indent=2))
