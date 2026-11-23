"""Test-only configuration. Never imported into the production server image."""
import re

KEY_FIELDS = frozenset({'api_key', 'learning_coach_api_key', 'career_advisor_api_key',
                        'operator_learning_coach_api_key', 'operator_career_advisor_api_key'})
DATABASE_IMAGE = 'pgvector/pgvector:0.8.1-pg17-bookworm@sha256:3e8b3adfd27b5707128f60956f62a793c3c9326ea8cfaf0eab7adccb5d700b21'
DATABASE_PASSWORD = 'fixture-only-postgres-password'


def environment(database_host, keys):
    if not isinstance(database_host,str) or not re.fullmatch(r'(?:hs-memory-db-[0-9a-f]{12}|specialist-validation-[0-9a-f]{32})', database_host):
        raise ValueError('only a fresh isolated fixture database alias is admitted')
    if (not isinstance(keys,dict) or set(keys) != KEY_FIELDS
            or any(not isinstance(v,str) or not re.fullmatch(r'fixture-[A-Za-z0-9_-]{1,100}',v) for v in keys.values())
            or len(set(keys.values())) != len(KEY_FIELDS)):
        raise ValueError('only explicit distinct synthetic fixture keys are admitted')
    env = {
        'HOME':'/tmp/fixture-home',
        'HINDSIGHT_API_DATABASE_URL':f'postgresql://fixture:{DATABASE_PASSWORD}@{database_host}:5432/fixture',
        'HINDSIGHT_API_HOST':'0.0.0.0', 'HINDSIGHT_API_PORT':'8888', 'HINDSIGHT_API_WORKERS':'1',
        'HINDSIGHT_API_WORKER_ENABLED':'true', 'HINDSIGHT_API_WORKER_ID':'isolated-memory-validation',
        'HINDSIGHT_API_LLM_PROVIDER':'none', 'HINDSIGHT_API_RETAIN_EXTRACTION_MODE':'chunks',
        'HINDSIGHT_API_ENABLE_OBSERVATIONS':'false', 'HINDSIGHT_API_ENABLE_AUTO_CONSOLIDATION':'false',
        'HINDSIGHT_API_RETAIN_BATCH_ENABLED':'false', 'HINDSIGHT_API_SKIP_LLM_VERIFICATION':'true',
        'HINDSIGHT_API_EMBEDDINGS_PROVIDER':'onnx',
        'HINDSIGHT_API_EMBEDDINGS_ONNX_MODEL_ID':'BAAI/bge-small-en-v1.5',
        'HINDSIGHT_API_EMBEDDINGS_ONNX_MODEL_PATH':'/models/onnx/model.onnx',
        'HINDSIGHT_API_EMBEDDINGS_ONNX_TOKENIZER_NAME_OR_PATH':'/models',
        'HINDSIGHT_API_EMBEDDINGS_ONNX_DIMENSIONS':'384', 'HINDSIGHT_API_EMBEDDINGS_ONNX_POOLING':'cls',
        'HINDSIGHT_API_EMBEDDINGS_ONNX_QUERY_PREFIX':'', 'HINDSIGHT_API_EMBEDDINGS_ONNX_PASSAGE_PREFIX':'',
        'HINDSIGHT_API_EMBEDDINGS_ONNX_DEVICE':'cpu', 'HINDSIGHT_API_RERANKER_PROVIDER':'rrf',
        'HINDSIGHT_API_DECISION_MODEL_PROVIDER':'none', 'HINDSIGHT_API_STORE_DOCUMENT_TEXT':'true',
        'HINDSIGHT_API_TENANT_EXTENSION':'homelab_hindsight_specialists:SpecialistTenantExtension',
        'HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION':'homelab_hindsight_specialists:SpecialistOperationValidator',
        'HINDSIGHT_API_TENANT_MCP_AUTH_DISABLED':'false', 'HINDSIGHT_API_MCP_ENABLED':'true',
        'HF_HUB_OFFLINE':'1', 'TRANSFORMERS_OFFLINE':'1', 'HF_HUB_DISABLE_TELEMETRY':'1',
        'HF_HUB_DISABLE_IMPLICIT_TOKEN':'1', 'OTEL_SDK_DISABLED':'true',
    }
    for prefix in ('HINDSIGHT_API_TENANT_', 'HINDSIGHT_API_OPERATION_VALIDATOR_'):
        env.update({prefix+name.upper():value for name,value in keys.items()})
    return env
