# Copyright (c) 2026 Drake Daniel Peters
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
#
# This file is part of the GCP AI Governor project.
# See the LICENSE file for full license text.

from daemon.constants import ALLOW_ROLES, IGNORE_EVENT_TYPES, REVOKE_ROLES


def evaluate_event(event):
    role = event.get("roleGranted")
    event_type = event.get("event_type")

    if role in REVOKE_ROLES:
        return "revoke"

    if role in ALLOW_ROLES:
        return "allow"

    if event_type in IGNORE_EVENT_TYPES:
        return "ignore"

    return "allow"
