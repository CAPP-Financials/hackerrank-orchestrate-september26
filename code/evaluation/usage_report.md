# Usage Report

Final full-dataset run that produced `output.csv`.

## Model

- Provider: Anthropic
- Model: claude-sonnet-5 (Stage 2 evidence extraction only -- the forecast/
  planning engine, Stages 1/3-9, is deterministic code, no model calls)

## Calls

- Total model calls: 209
  - message_extraction: 198 calls, 224601 input tokens, 31328 output tokens
  - image_extraction: 11 calls, 25023 input tokens, 1059 output tokens

## Tokens

- Total input tokens: 249624
- Total output tokens: 32387
- Total tokens: 282011
- Requests processed: 250
- Average tokens per request: 1128.0

## Cost

- Rate: $3.0/1M input tokens, $15.0/1M output tokens (Anthropic list pricing, Sonnet-5 tier)
- Estimated total cost: $1.2347
- Estimated cost per request: $0.004939
