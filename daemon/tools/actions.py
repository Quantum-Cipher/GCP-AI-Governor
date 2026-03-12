# Copyright (c) 2026 Drake Daniel Peters
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
#
# This file is part of the GCP AI Governor project.
# See the LICENSE file for full license text.

import logging

logger = logging.getLogger("gcp-ai-governor")


def execute_action(decision, event):
    if decision == "revoke":
        logger.info("Simulated remediation: revoking role")
        return {
            "action": "revoke",
            "principal": event.get("principal"),
            "role": event.get("roleGranted")
        }

    if decision == "ignore":
        logger.info("Simulated remediation: ignoring event")
        return {
            "action": "ignore"
        }

    logger.info("Simulated remediation: no action required")
    return {
        "action": "none"
    }
