# Supervisor Agent Lambda

Container-based AWS Lambda version of the local `src/agents/supervisor` agent.

Build the image from the repository root:

```bash
python backend/supervisor_agent/package_docker.py
```

After provisioning the `sidechart-supervisor-agent` ECR repository and Lambda function, deploy with:

```bash
python backend/supervisor_agent/package_docker.py --deploy
```

Direct invocation payload:

```json
{
  "tickers": ["MSFT"],
  "sellside_research": "Completed sell-side research output",
  "pipeline_results": {
    "status": "complete",
    "weights": [{"ticker": "MSFT", "weights": 1.0}]
  },
  "current_positions": [{"ticker": "MSFT", "position": 10}]
}
```

Required Lambda configuration:

- Memory: at least 2048 MB
- Timeout: 15 minutes
- Ephemeral storage: at least 2048 MB
- Environment: `BEDROCK_MODEL_ID`, `BEDROCK_REGION`, and the API/IBKR
  variables used by `src/agents/supervisor/tools.py`
- IAM: permission to invoke the configured Amazon Bedrock model and any AWS
  services used by the supervisor tools

Run the mocked unit tests without calling AWS, Bedrock, or IBKR:

```bash
python -m unittest -v backend.supervisor_agent.test_unit
```

After deployment, invoke the actual Lambda with:

```bash
python backend/supervisor_agent/test_full.py
```
