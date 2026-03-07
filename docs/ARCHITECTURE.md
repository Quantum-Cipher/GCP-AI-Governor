# Architecture

## Current State
The current system validates a local governance control loop:

event -> policy evaluation -> decision -> simulated remediation

## Current Components
- Flask governance daemon
- Policy engine
- Action execution stub
- Local simulator
- Smoke test
- GitHub Actions CI

## Future State
The intended cloud-native path is:

Cloud Audit Logs -> Eventarc -> Cloud Run -> Vertex AI -> Tool Execution Layer -> Cloud Logging / BigQuery

## Safety Posture
- `LIVE_MODE=false` by default
- dry-run first
- auditable logs
- bounded iteration concepts for future reasoning loops
