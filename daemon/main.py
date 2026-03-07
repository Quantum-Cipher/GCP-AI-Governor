from flask import Flask, request, jsonify
from policies.policy_engine import evaluate_event
from tools.actions import execute_action
import json

app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "gcp-ai-governor"
    }), 200

@app.route("/event", methods=["POST"])
def receive_event():
    payload = request.get_json(force=True, silent=False)

    print("\nEvent received:")
    print(json.dumps(payload, indent=2))

    decision = evaluate_event(payload)

    print("\nDecision from policy engine:")
    print(decision)

    result = execute_action(decision, payload)

    return jsonify({
        "decision": decision,
        "action_result": result
    }), 200

if __name__ == "__main__":
    print("AI Cloud Governance Agent running")
    print("Listening on port 8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
