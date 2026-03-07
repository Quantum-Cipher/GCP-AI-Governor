# Copyright (c) 2026 Drake Daniel Peters
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)

import os
import json
import logging
import time
import uuid
from cloudevents.http import CloudEvent
from functions_framework import cloud_event
import vertexai
from vertexai.generative_models import GenerativeModel, Tool, FunctionDeclaration, GenerationConfig, Part, Content
from google.cloud import logging as cloud_logging
from google.cloud import billing_v1

# Configuration
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "daemonic-codex-poc-1")
REGION = os.environ.get("REGION", "us-central1")
LIVE_MODE = os.environ.get("LIVE_MODE", "false").lower() == "true"
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "8"))

# Logger Setup
logger = logging.getLogger("daemonic-governor")
logging.basicConfig(level=logging.INFO)
try:
    cloud_logging.Client(project=PROJECT_ID).setup_logging()
except Exception:
    pass

vertexai.init(project=PROJECT_ID, location=REGION)

# Tool Definitions
link_billing_func = FunctionDeclaration(
    name="link_billing_account",
    description="Link a project to a billing account. Always check LIVE_MODE.",
    parameters={
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "billing_account": {"type": "string"}
        },
        "required": ["project_id", "billing_account"]
    }
)

tools = Tool(function_declarations=[link_billing_func])
model = GenerativeModel(
    "gemini-2.5-flash-001",
    tools=[tools],
    generation_config=GenerationConfig(temperature=0.1),
    system_instruction="You are the DaemonicCodex AI Governor. Analyze events. Use dry-run unless LIVE_MODE is true."
)

def execute_tool(fc):
    if fc.name == "link_billing_account":
        if not LIVE_MODE:
            return f"[DRY-RUN] Would link {fc.args['project_id']} to {fc.args['billing_account']}"
        # Live path logic here...
        return "[LIVE] Execution would happen here."
    return "Unknown tool"

@cloud_event
def governor_handler(event: CloudEvent):
    payload = event.data
    method = payload.get("protoPayload", {}).get("methodName", "unknown")
    
    # ReAct Loop
    contents = [Content(role="user", parts=[Part.from_text(f"Audit event: {method}. Enforce policy.")])]
    for i in range(MAX_ITERATIONS):
        response = model.generate_content(contents)
        if not response.candidates[0].function_calls:
            logger.info(f"Final Decision: {response.text}")
            return
        
        contents.append(response.candidates[0].content)
        tool_results = []
        for fc in response.candidates[0].function_calls:
            result = execute_tool(fc)
            tool_results.append(Part.from_function_response(name=fc.name, response={"result": result}))
        contents.append(Content(role="user", parts=tool_results))

