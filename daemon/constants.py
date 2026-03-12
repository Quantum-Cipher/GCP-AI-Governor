# Copyright (c) 2026 Drake Daniel Peters
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
#
# This file is part of the GCP AI Governor project.
# See the LICENSE file for full license text.

# Roles that trigger an immediate access revocation.
REVOKE_ROLES = frozenset({
    "roles/owner",
    "roles/editor",
    "roles/iam.serviceAccountAdmin",
    "roles/resourcemanager.projectIamAdmin",
})

# Roles that are explicitly permitted without further action.
ALLOW_ROLES = frozenset({
    "roles/viewer",
    "roles/browser",
})

# Event types that should be silently ignored (e.g. health signals).
IGNORE_EVENT_TYPES = frozenset({
    "heartbeat",
    "healthcheck",
    "noop",
})
