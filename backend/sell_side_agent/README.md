# Sell-side Agent Lambda

Container-based AWS Lambda version of the local `src/agents/research` agent.

Build the image from the repository root:

```bash
python backend/sell_side_agent/package_docker.py
```

After provisioning the `sidechart-sell-side-agent` ECR repository and Lambda function, deploy with:

```bash
python backend/sell_side_agent/package_docker.py --deploy
```

Direct invocation payload:

```json
{
  "topic": "Microsoft earnings and valuation",
  "tickers": ["MSFT"]
}
```

Required Lambda configuration:

- Memory: at least 2048 MB
- Timeout: 15 minutes
- Ephemeral storage: at least 2048 MB
- Environment: `BEDROCK_MODEL_ID`, `BEDROCK_REGION`, and the ingestion API
  variables used by `src/agents/research/tools.py`
- IAM: permission to invoke the configured Amazon Bedrock model

Run the mocked unit tests without calling AWS or Bedrock:

```bash
python -m unittest -v backend.sell_side_agent.test_unit
```

After deployment, invoke the actual Lambda with:

```bash
python backend/sell_side_agent/test_full.py
```
