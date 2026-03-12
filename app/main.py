# Copyright (c) 2026 Drake Daniel Peters
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Tuple
import threading

import functions_framework
from flask import Request, jsonify

import vertexai
from vertexai.generative_models import GenerativeModel
from google.cloud import logging as cloud_logging
from confluent_kafka import Consumer

# ============================================================
# Configuration
# ============================================================

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
REGION = os.getenv("REGION", "us-central1").strip()
MODEL_NAME = os.getenv("VERTEX_MODEL", "gemini-2.5-flash").strip()
LIVE_MODE = os.getenv("LIVE_MODE", "false").strip().lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
SERVICE_NAME = os.getenv("K_SERVICE", "daemonic-codex-ai-governor").strip()
MAX_INPUT_BYTES = int(os.getenv("MAX_INPUT_BYTES", "65536"))
ENABLE_VERTEX_REASONING = os.getenv("ENABLE_VERTEX_REASONING", "true").strip().lower() == "true"
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "").strip()
KAFKA_SECURITY_PROTOCOL = "SASL_SSL"
KAFKA_SASL_MECHANISM = "OAUTHBEARER"
GOVERNANCE_TOPIC = "governance.audit.v1"

# ============================================================
# Logging
# ============================================================

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(SERVICE_NAME)

try:
    if PROJECT_ID:
        cloud_logging.Client(project=PROJECT_ID).setup_logging()
except Exception as exc:
    logger.warning("cloud_logging_setup_failed: %s", exc)


def structured_log(entry: Dict[str, Any], severity: str = "INFO") -> None:
    payload = {
        "service": SERVICE_NAME,
        "severity": severity,
        "timestamp": int(time.time()),
        **entry,
    }
    logger.log(getattr(logging, severity.upper(), logging.INFO), json.dumps(payload, sort_keys=True))


# ============================================================
# Kafka Consumer Thread
# ============================================================

def _token_provider():
    from google.auth.transport.requests import Request
    import google.auth

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    return credentials.token


def start_consumer_loop():
    def _loop():
        consumer = Consumer(
            {
                "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
                "security.protocol": KAFKA_SECURITY_PROTOCOL,
                "sasl.mechanism": KAFKA_SASL_MECHANISM,
                "sasl.oauthbearer.token": _token_provider(),
                "group.id": "ai-governor-consumer",
                "auto.offset.reset": "earliest",
            }
        )
        consumer.subscribe([GOVERNANCE_TOPIC])

        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                structured_log(
                    {"type": "kafka_poll_error", "error": str(msg.error())},
                    severity="ERROR",
                )
                continue

            try:
                payload = json.loads(msg.value().decode("utf-8"))
                evaluation = evaluate_event(payload)
                action_result = execute_action(payload, evaluation)
                structured_log(
                    {
                        "type": "kafka_event_processed",
                        "payload": payload,
                        "evaluation": evaluation,
                        "action": action_result,
                    }
                )
            except Exception as exc:
                structured_log(
                    {"type": "kafka_event_processing_error", "error": str(exc)},
                    severity="ERROR",
                )

    if KAFKA_BOOTSTRAP_SERVERS:
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        structured_log({"type": "kafka_consumer_started"})
    else:
        structured_log(
            {"type": "kafka_consumer_skipped", "reason": "No bootstrap servers configured"},
            severity="WARNING",
        )


# ============================================================
# Vertex AI initialization
# ============================================================

_model: GenerativeModel | None = None
_vertex_init_attempted = False


def get_model() -> GenerativeModel:
    global _model, _vertex_init_attempted

    if _model is not None:
        return _model

    if not PROJECT_ID:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is required for Vertex AI initialization")

    if not _vertex_init_attempted:
        vertexai.init(project=PROJECT_ID, location=REGION)
        _vertex_init_attempted = True

    _model = GenerativeModel(MODEL_NAME)
    return _model


# ============================================================
# Governance policy
# ============================================================

def deterministic_policy(event: Dict[str, Any]) -> Tuple[str, str]:
    event_type = str(event.get("event_type", "")).strip()
    role = str(event.get("roleGranted", "")).strip()

    if role == "roles/owner":
        return "revoke", "owner_role_grant_detected"

    if role in {
        "roles/editor",
        "roles/iam.serviceAccountAdmin",
        "roles/resourcemanager.projectIamAdmin",
    }:
        return "revoke", "high_privilege_role_grant_detected"

    if role in {"roles/viewer", "roles/browser"}:
        return "allow", "read_only_role_detected"

    if event_type in {"heartbeat", "healthcheck", "noop"}:
        return "ignore", "non_actionable_event"

    return "allow", "default_allow"


def build_reasoning_prompt(
    event: Dict[str, Any],
    deterministic_decision: str,
    deterministic_reason: str,
) -> str:
    return f"""
You are an AI cloud governance analyst operating in DRY-RUN-FIRST mode.

Your task:
1. Review the infrastructure event.
2. Confirm whether the deterministic governance policy is reasonable.
3. Return strict JSON only.

Rules:
- Never recommend live mutation directly.
- Treat all actions as advisory unless LIVE_MODE is explicitly enabled.
- Keep the output concise and machine-readable.

Event:
{json.dumps(event, indent=2, sort_keys=True)}

Deterministic policy result:
{json.dumps({"decision": deterministic_decision, "reason": deterministic_reason}, indent=2)}

Return JSON with exactly these keys:
{{
  "decision": "allow|revoke|ignore",
  "reason": "short_machine_reason",
  "risk_level": "low|medium|high",
  "summary": "short human-readable explanation"
}}
""".strip()


def vertex_reasoning(
    event: Dict[str, Any],
    deterministic_decision: str,
    deterministic_reason: str,
) -> Dict[str, Any]:
    prompt = build_reasoning_prompt(event, deterministic_decision, deterministic_reason)
    model = get_model()
    response = model.generate_content(prompt)

    text = getattr(response, "text", "") or ""
    cleaned = text.strip()

    try:
        return json.loads(cleaned)
    except Exception:
        return {
            "decision": deterministic_decision,
            "reason": "vertex_response_non_json_fallback",
            "risk_level": "medium" if deterministic_decision == "revoke" else "low",
            "summary": cleaned[:1000],
        }


def evaluate_event(event: Dict[str, Any]) -> Dict[str, Any]:
    deterministic_decision, deterministic_reason = deterministic_policy(event)

    result: Dict[str, Any] = {
        "decision": deterministic_decision,
        "reason": deterministic_reason,
        "risk_level": "high" if deterministic_decision == "revoke" else "low",
        "summary": "Deterministic policy evaluation completed.",
        "evaluation_mode": "deterministic_only",
    }

    if not ENABLE_VERTEX_REASONING:
        return result

    try:
        ai_result = vertex_reasoning(event, deterministic_decision, deterministic_reason)
        result.update(
            {
                "decision": ai_result.get("decision", deterministic_decision),
                "reason": ai_result.get("reason", deterministic_reason),
                "risk_level": ai_result.get("risk_level", result["risk_level"]),
                "summary": ai_result.get("summary", result["summary"]),
                "evaluation_mode": "deterministic_plus_vertex",
            }
        )
    except Exception as exc:
        structured_log(
            {
                "type": "vertex_reasoning_failure",
                "error": str(exc),
                "fallback_decision": deterministic_decision,
            },
            severity="WARNING",
        )

    return result


def execute_action(event: Dict[str, Any], evaluation: Dict[str, Any]) -> Dict[str, Any]:
    decision = evaluation["decision"]

    if decision == "revoke":
        return {
            "status": "EXECUTED" if LIVE_MODE else "DRY_RUN_SUCCESS",
            "action": "revoke_access",
            "principal": event.get("principal", "unknown"),
            "role": event.get("roleGranted", "unknown"),
            "resource": event.get("resource", "unknown"),
            "live_mode": LIVE_MODE,
        }

    if decision == "ignore":
        return {
            "status": "IGNORED",
            "action": "none",
            "live_mode": LIVE_MODE,
        }

    return {
        "status": "ALLOWED",
        "action": "none",
        "live_mode": LIVE_MODE,
    }


# ============================================================
# Request helpers
# ============================================================

def parse_request_payload(request: Request) -> Dict[str, Any]:
    raw = request.get_data(cache=False, as_text=False) or b""

    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"request payload exceeds MAX_INPUT_BYTES={MAX_INPUT_BYTES}")

    if not raw:
        return {}

    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid_json_payload: {exc}") from exc


def normalize_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    proto = payload.get("protoPayload", {})

    if proto:
        return {
            "event_id": payload.get("event_id", str(uuid.uuid4())),
            "timestamp": payload.get("timestamp", int(time.time())),
            "event_type": proto.get("methodName", "unknown"),
            "principal": proto.get("authenticationInfo", {}).get("principalEmail", "unknown"),
            "resource": proto.get("resourceName", "unknown"),
            "roleGranted": payload.get("roleGranted", ""),
            "raw_payload": payload,
        }

    return {
        "event_id": payload.get("event_id", str(uuid.uuid4())),
        "timestamp": payload.get("timestamp", int(time.time())),
        "event_type": payload.get("event_type", "unknown"),
        "principal": payload.get("principal", "unknown"),
        "resource": payload.get("resource", "unknown"),
        "roleGranted": payload.get("roleGranted", ""),
        "raw_payload": payload,
    }


# ============================================================
# Functions Framework entrypoint
# ============================================================

@functions_framework.http
def governor(request: Request):
    request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))

    if request.method == "GET" and request.path in {"/", "/health"}:
        return jsonify(
            {
                "status": "ok",
                "service": SERVICE_NAME,
                "live_mode": LIVE_MODE,
                "vertex_reasoning_enabled": ENABLE_VERTEX_REASONING,
                "model": MODEL_NAME,
                "region": REGION,
            }
        ), 200

    if request.method != "POST":
        return jsonify(
            {
                "error": "method_not_allowed",
                "allowed_methods": ["GET", "POST"],
                "request_id": request_id,
            }
        ), 405

    try:
        payload = parse_request_payload(request)
        event = normalize_event(payload)

        structured_log(
            {
                "type": "event_received",
                "request_id": request_id,
                "event_id": event["event_id"],
                "principal": event["principal"],
                "resource": event["resource"],
                "event_type": event["event_type"],
                "roleGranted": event["roleGranted"],
                "live_mode": LIVE_MODE,
            }
        )

        evaluation = evaluate_event(event)
        action_result = execute_action(event, evaluation)

        response = {
            "request_id": request_id,
            "event_id": event["event_id"],
            "evaluation": evaluation,
            "action_result": action_result,
        }

        structured_log(
            {
                "type": "governance_decision",
                "request_id": request_id,
                "event_id": event["event_id"],
                "decision": evaluation["decision"],
                "reason": evaluation["reason"],
                "risk_level": evaluation["risk_level"],
                "action_status": action_result["status"],
                "live_mode": LIVE_MODE,
            }
        )

        return jsonify(response), 200

    except ValueError as exc:
        structured_log(
            {
                "type": "bad_request",
                "request_id": request_id,
                "error": str(exc),
            },
            severity="WARNING",
        )
        return jsonify(
            {
                "error": "bad_request",
                "message": str(exc),
                "request_id": request_id,
            }
        ), 400

    except Exception as exc:
        structured_log(
            {
                "type": "internal_error",
                "request_id": request_id,
                "error": str(exc),
            },
            severity="ERROR",
        )
        return jsonify(
            {
                "error": "internal_error",
                "request_id": request_id,
            }
        ), 500


start_consumer_loop()
