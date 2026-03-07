#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="numeric-axe-zll0l"
BQ_DATASET="governor_audit"
SINK_NAME="governor-transcript-sink"

gcloud logging sinks create "$SINK_NAME" \
  "bigquery.googleapis.com/projects/$PROJECT_ID/datasets/$BQ_DATASET" \
  --log-filter='jsonPayload.type="transcript"' \
  --project="$PROJECT_ID"

SINK_SERVICE_ACCOUNT=$(gcloud logging sinks describe "$SINK_NAME" \
  --format='value(writerIdentity)' \
  --project="$PROJECT_ID")

bq update \
  --project_id="$PROJECT_ID" \
  --dataset="$BQ_DATASET" \
  --source <(cat <<JSON
{
  "access": [
    {
      "role": "WRITER",
      "userByEmail": "${SINK_SERVICE_ACCOUNT#serviceAccount:}"
    }
  ]
}
JSON
)
