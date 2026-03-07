# Copyright (c) 2026 Drake Daniel Peters
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)

import os
import json
import logging
from flask import Flask, request, jsonify

try:
    import vertexai
    from vertexai.generative_models import GenerativeModel, Part, Tool, FunctionDeclaration
    from google.cloud import logging as cloud_logging
    VERTEX_AVAILABLE = True
except Exception:
    VERTEX_AVAILABLE = False

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "numeric-axe-zll0l")
REGION = os.environ.get("REGION", "us-central1")
LIVE_MODE = os.environ.get("LIVE_MODE", "false").lower() == "true"
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "8"))

app = Flask(__name__)
logger = logging.getLogger("gcp-ai-governor")
logging.basicConfig(level=logging.INFO)

if VERTEX_AVAILABLE:
    try:
        cloud_logging.Client(project=PROJECT_ID).setup_logging()
    except Exception:
        pass

def structured_log(entry: dict) -> None:
    logger.info(json.dumps(entry))

def evaluate_event(event: dict) -> str:
    role = event.get("roleGranted", "")
    event_type = event.get("event_type", "")

    if role == "roles/owner":
        return "revoke"

    if role in {
        "roles/editor",
        "roles/iam.serviceAccountAdmin",
        "roles/resourcemanager.projectIamAdmin",
    }:
        return "revoke"

    if role in {"roles/viewer", "roles/browser"}:
        return "allow"

    if event_type in {"heartbeat", "healthcheck", "noop"}:
        return "ignore"

    return "allow"

def execute_action(decision: str, event: dict) -> dict:
    if decision == "revoke":
        result = {
            "status": "DRY_RUN_SUCCESS" if not LIVE_MODE else "EXECUTED",
            "action": "revoke_access",
            "principal": event.get("principal", "unknown"),
            "role": event.get("roleGranted", "unknown"),
            "live_mode": LIVE_MODE,
        }
        structured_log({"type": "transcript", "decision": decision, "result": result})
        return result

    if decision == "ignore":
        result = {"status": "IGNORED", "action": "none", "live_mode": LIVE_MODE}
        structured_log({"type": "transcript", "decision": decision, "result": result})
        return result

    result = {"status": "ALLOWED", "action": "none", "live_mode": LIVE_MODE}
    structured_log({"type": "transcript", "decision": decision, "result": result})
    return result

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "gcp-ai-governor", "live_mode": LIVE_MODE}), 200

@app.route("/event", methods=["POST"])
def receive_event():
    payload = request.get_json(force=True, silent=False)

    structured_log({"type": "event_received", "payload": payload})

    decision = evaluate_event(payload)
    action_result = execute_action(decision, payload)

    response = {
        "decision": decision,
        "action_result": action_result,
    }
    return jsonify(response), 200

@app.route("/", methods=["POST"])
def root_event():
    payload = request.get_json(force=True, silent=True) or {}
    proto = payload.get("protoPayload", {})
    event = {
        "event_type": proto.get("methodName", "unknown"),
        "principal": proto.get("authenticationInfo", {}).get("principalEmail", "unknown"),
        "resource": proto.get("resourceName", "unknown"),
        "roleGranted": proto.get("roleGranted", ""),
    }
    decision = evaluate_event(event)
    action_result = execute_action(decision, event)
    return jsonify({"decision": decision, "action_result": action_result}), 200

if __name__ == "__main__":
    print("AI Cloud Governance Agent running")
    print("Listening on port 8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
