# Copyright (c) 2026 Drake Daniel Peters
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import functions_framework
from cloudevents.http import CloudEvent
from confluent_kafka import Consumer
from flask import Request, jsonify
from google.cloud import logging as cloud_logging
import vertexai
from vertexai.generative_models import GenerativeModel

from flask import Flask

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return "OK", 200

from decision_record import (
    ActionResultContext,
    DecisionRecord,
    DeterministicPolicyContext,
    EventContext,
    KafkaContext,
    ResourceContext,
    RuntimeContext,
    VertexAdvisoryContext,
)

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
KAFKA_SECURITY_PROTOCOL = os.getenv("KAFKA_SECURITY_PROTOCOL", "SASL_SSL").strip()
KAFKA_SASL_MECHANISM = os.getenv("KAFKA_SASL_MECHANISM", "OAUTHBEARER").strip()
GOVERNANCE_TOPIC = os.getenv("GOVERNANCE_TOPIC", "governance.audit.v1").strip()

HIGH_RISK_ROLES = {
    "roles/owner",
    "roles/editor",
    "roles/iam.serviceAccountAdmin",
}

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
        "severity": severity.upper(),
        "timestamp": int(time.time()),
        **entry,
    }
    logger.log(
        getattr(logging, severity.upper(), logging.INFO),
        json.dumps(payload, sort_keys=True, default=str),
    )


# ============================================================
# Kafka bootstrap / future event spine
# ============================================================

_consumer_started = False
_consumer_lock = threading.Lock()


def _token_provider(_: Optional[str] = None) -> Optional[str]:
    """
    Placeholder for future Kafka OAUTHBEARER flow.
    Current MVP does not use Kafka auth tokens.
    """
    return None


def start_consumer_loop() -> None:
    global _consumer_started

    with _consumer_lock:
        if _consumer_started:
            return
        _consumer_started = True

    if not KAFKA_BOOTSTRAP_SERVERS:
        structured_log(
            {
                "type": "kafka_consumer_skipped",
                "reason": "No bootstrap servers configured",
            },
            severity="WARNING",
        )
        return

    try:
        Consumer(
            {
                "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
                "security.protocol": KAFKA_SECURITY_PROTOCOL,
                "sasl.mechanism": KAFKA_SASL_MECHANISM,
                "group.id": f"{SERVICE_NAME}-consumer",
                "auto.offset.reset": "latest",
            }
        )
        structured_log(
            {
                "type": "kafka_consumer_initialized",
                "topic": GOVERNANCE_TOPIC,
            },
            severity="INFO",
        )
    except Exception as exc:
        structured_log(
            {
                "type": "kafka_consumer_failed",
                "error": str(exc),
            },
            severity="WARNING",
        )


start_consumer_loop()

# ============================================================
# Vertex reasoning
# ============================================================

_vertex_model: Optional[GenerativeModel] = None
_vertex_lock = threading.Lock()


def get_model() -> GenerativeModel:
    global _vertex_model

    if not PROJECT_ID:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is required for Vertex AI initialization")

    with _vertex_lock:
        if _vertex_model is None:
            vertexai.init(project=PROJECT_ID, location=REGION)
            _vertex_model = GenerativeModel(MODEL_NAME)

    return _vertex_model


def build_reasoning_prompt(event: Dict[str, Any]) -> str:
    return (
        "You are a cloud governance advisor. "
        "Given this event, summarize risk and recommend an action in one short paragraph.\n\n"
        f"Event:\n{json.dumps(event, indent=2, sort_keys=True, default=str)}"
    )


def vertex_reasoning(event: Dict[str, Any]) -> Dict[str, Any]:
    if not ENABLE_VERTEX_REASONING:
        return {
            "enabled": False,
            "status": "skipped",
            "model": MODEL_NAME,
            "latency_ms": 0,
            "summary": None,
            "error": None,
        }

    started = time.time()

    try:
        model = get_model()
        prompt = build_reasoning_prompt(event)
        response = model.generate_content(prompt)
        summary = getattr(response, "text", None)

        return {
            "enabled": True,
            "status": "success",
            "model": MODEL_NAME,
            "latency_ms": int((time.time() - started) * 1000),
            "summary": summary,
            "error": None,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "status": "error",
            "model": MODEL_NAME,
            "latency_ms": int((time.time() - started) * 1000),
            "summary": None,
            "error": str(exc),
        }


# ============================================================
# Event normalization + policy
# ============================================================

def parse_request_payload(event: CloudEvent) -> Dict[str, Any]:
    data = getattr(event, "data", None)

    if data is None:
        return {}

    if isinstance(data, dict):
        return data

    if isinstance(data, (str, bytes)):
        try:
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            return json.loads(data)
        except Exception:
            return {"raw_payload": data}

    return {"raw_payload": data}


def _extract_role_from_audit_payload(payload: Dict[str, Any]) -> str:
    proto = payload.get("protoPayload", {}) or {}
    request = proto.get("request", {}) or {}

    policy = request.get("policy", {}) or {}
    bindings = policy.get("bindings", []) or []

    for binding in bindings:
        role = binding.get("role")
        if role:
            return role

    role_granted = payload.get("roleGranted", "")
    if role_granted:
        return role_granted

    return ""


def normalize_event(payload: Dict[str, Any], event: CloudEvent) -> Dict[str, Any]:
    attrs = getattr(event, "_attributes", {}) or {}
    proto = payload.get("protoPayload", {}) or {}

    principal = (
        proto.get("authenticationInfo", {}).get("principalEmail")
        or payload.get("principal")
        or "unknown"
    )
    resource = proto.get("resourceName") or payload.get("resource") or "unknown"
    method_name = proto.get("methodName") or payload.get("event_type") or "unknown"
    role_granted = _extract_role_from_audit_payload(payload)

    return {
        "event_id": attrs.get("id", payload.get("event_id", str(uuid.uuid4()))),
        "timestamp": attrs.get("time", payload.get("timestamp", int(time.time()))),
        "event_type": attrs.get("type", "unknown"),
        "source": attrs.get("source", "unknown"),
        "subject": attrs.get("subject"),
        "method_name": method_name,
        "service_name": proto.get("serviceName"),
        "principal": principal,
        "resource": resource,
        "roleGranted": role_granted,
        "raw_payload": payload,
    }


def deterministic_policy(event: Dict[str, Any]) -> Dict[str, Any]:
    role = (event.get("roleGranted") or "").strip()

    if role in HIGH_RISK_ROLES:
        return {
            "decision": "revoke",
            "reason": "high_risk_role_binding",
            "risk_level": "high",
            "evaluation_mode": "deterministic_only",
            "summary": f"High-risk role detected: {role}",
            "rule_id": "high_risk_role_binding",
            "rules_fired": ["high_risk_role_binding"],
        }

    return {
        "decision": "allow",
        "reason": "default_allow",
        "risk_level": "low",
        "evaluation_mode": "deterministic_only",
        "summary": "Deterministic policy evaluation completed.",
        "rule_id": "default_allow",
        "rules_fired": ["default_allow"],
    }


def evaluate_event(event: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    policy = deterministic_policy(event)
    advisory = vertex_reasoning(event)

    if advisory.get("status") == "error":
        structured_log(
            {
                "type": "vertex_reasoning_failure",
                "error": advisory.get("error"),
                "fallback_decision": policy.get("decision"),
            },
            severity="WARNING",
        )

    return policy, advisory


def execute_action(event: Dict[str, Any], evaluation: Dict[str, Any]) -> Dict[str, Any]:
    decision = evaluation.get("decision", "allow")

    if not LIVE_MODE:
        if decision == "revoke":
            return {
                "executed": False,
                "action": "revoke_access",
                "status": "DRY_RUN_SUCCESS",
                "dry_run": True,
            }

        return {
            "executed": False,
            "action": "none",
            "status": "ALLOWED",
            "dry_run": True,
        }

    if decision == "revoke":
        return {
            "executed": True,
            "action": "revoke_access",
            "status": "EXECUTED",
            "dry_run": False,
        }

    return {
        "executed": False,
        "action": "none",
        "status": "ALLOWED",
        "dry_run": False,
    }


# ============================================================
# Functions Framework entrypoints
# ============================================================

@functions_framework.http
def health(request: Request):
    return jsonify(
        {
            "status": "ok",
            "service": SERVICE_NAME,
            "model": MODEL_NAME,
            "region": REGION,
            "live_mode": LIVE_MODE,
            "vertex_reasoning_enabled": ENABLE_VERTEX_REASONING,
        }
    )


@functions_framework.cloud_event
def governor(event: CloudEvent):
    request_id = str(uuid.uuid4())

    payload = parse_request_payload(event)
    normalized = normalize_event(payload, event)

    structured_log(
        {
            "type": "event_received",
            "event_id": normalized["event_id"],
            "request_id": request_id,
            "event_type": normalized["method_name"],
            "principal": normalized["principal"],
            "resource": normalized["resource"],
            "roleGranted": normalized["roleGranted"],
            "live_mode": LIVE_MODE,
        },
        severity="INFO",
    )

    evaluation, advisory = evaluate_event(normalized)
    action_result = execute_action(normalized, evaluation)

    decision_record = DecisionRecord(
        live_mode=LIVE_MODE,
        event_id=normalized["event_id"],
        request_id=request_id,
        evaluation_mode=evaluation.get("evaluation_mode", "deterministic_only"),
        status=action_result.get("status", "UNKNOWN"),
        decision=evaluation.get("decision", "unknown"),
        reason=evaluation.get("reason", "unspecified"),
        risk_level=evaluation.get("risk_level", "unknown"),
        summary=evaluation.get("summary", "Decision recorded."),
        event=EventContext(
            source=normalized.get("source"),
            type=normalized.get("event_type"),
            subject=normalized.get("subject"),
            time=str(normalized.get("timestamp")),
            service_name=normalized.get("service_name"),
            method_name=normalized.get("method_name"),
            resource_name=normalized.get("resource"),
            principal_email=normalized.get("principal"),
        ),
        resource=ResourceContext(
            project_id=PROJECT_ID or "unknown",
            location=REGION,
            target_type="project",
            target_name=normalized.get("resource"),
        ),
        deterministic_policy=DeterministicPolicyContext(
            matched=True,
            rule_id=evaluation.get("rule_id"),
            rules_fired=evaluation.get("rules_fired", []),
        ),
        vertex_advisory=VertexAdvisoryContext(
            enabled=bool(advisory.get("enabled", False)),
            status=str(advisory.get("status", "skipped")),
            model=advisory.get("model"),
            latency_ms=int(advisory.get("latency_ms", 0) or 0),
            summary=advisory.get("summary"),
            error=advisory.get("error"),
        ),
        kafka=KafkaContext(
            enabled=bool(KAFKA_BOOTSTRAP_SERVERS),
            status="enabled" if KAFKA_BOOTSTRAP_SERVERS else "skipped",
            topic=GOVERNANCE_TOPIC if KAFKA_BOOTSTRAP_SERVERS else None,
            error=None if KAFKA_BOOTSTRAP_SERVERS else "No bootstrap servers configured",
        ),
        action_result=ActionResultContext(
            executed=bool(action_result.get("executed", False)),
            action=str(action_result.get("action", "none")),
            status=str(action_result.get("status", "UNKNOWN")),
            dry_run=bool(action_result.get("dry_run", not LIVE_MODE)),
        ),
        runtime=RuntimeContext(
            region=REGION,
            revision=os.getenv("K_REVISION"),
            instance_id=os.getenv("K_INSTANCE"),
        ),
    )

    structured_log(decision_record.to_dict(), severity="INFO")

    structured_log(
        {
            "type": "governance_decision",
            "event_id": normalized["event_id"],
            "request_id": request_id,
            "decision": evaluation.get("decision"),
            "reason": evaluation.get("reason"),
            "risk_level": evaluation.get("risk_level"),
            "action_status": action_result.get("status"),
            "live_mode": LIVE_MODE,
        },
        severity="INFO",
    )

    return {
        "status": action_result.get("status", "UNKNOWN"),
        "event_id": normalized["event_id"],
        "request_id": request_id,
        "evaluation": {
            "decision": evaluation.get("decision"),
            "evaluation_mode": evaluation.get("evaluation_mode"),
            "reason": evaluation.get("reason"),
            "risk_level": evaluation.get("risk_level"),
            "summary": evaluation.get("summary"),
        },
        "action_result": action_result,
    }
