# fix-ai-batch-validator

- AIJobBatch prompt context limit restored to 2000 chars so oversized batches raise ValidationError with `max is 2000`.
- Validation: `py -3 -m pytest tests/test_ai_pipeline_contracts.py -q` passed (7 passed); `py -3 -m pytest -q` passed (623 passed).
