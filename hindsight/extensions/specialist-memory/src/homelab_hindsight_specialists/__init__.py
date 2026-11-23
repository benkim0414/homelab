"""Fixed Hindsight identities and policy, admitted only behind the ASGI boundary."""

from dataclasses import dataclass
from hmac import compare_digest
import os
import re

from hindsight_api.config import get_config
from hindsight_api.extensions.tenant import AuthenticationError, Tenant, TenantContext, TenantExtension
from hindsight_api.extensions.operation_validator import (
    BankListResult, BankListScope, OperationValidatorExtension, ValidationResult,
)


@dataclass(frozen=True)
class Identity:
    name: str
    bank: str
    schema: str
    read_only: bool = True


SPECIALISTS = (
    Identity("learning_coach", "infinite-recursion", "user_learning_coach"),
    Identity("career_advisor", "next-level", "user_career_advisor"),
)



def _legacy_schema():
    schema = get_config().database_schema
    if (not isinstance(schema, str) or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema)
            or schema.startswith("pg_") or schema == "information_schema"
            or schema in {identity.schema for identity in SPECIALISTS}):
        raise ValueError("Invalid or colliding legacy schema")
    return schema


class SpecialistTenantExtension(TenantExtension):
    """Preserve legacy auth/schema; require bound ingress for non-legacy callers."""

    def __init__(self, config: dict[str, str]):
        if "HINDSIGHT_API_MCP_AUTH_TOKEN" in os.environ:
            raise ValueError("Legacy MCP transport authentication override is forbidden")
        required = {"api_key", "learning_coach_api_key", "career_advisor_api_key"}
        optional = {"mcp_auth_disabled", "operator_learning_coach_api_key", "operator_career_advisor_api_key"}
        if not isinstance(config, dict) or not required <= config.keys() or config.keys() - required - optional:
            raise ValueError("Invalid specialist key configuration")
        mcp_bypass = config.get("mcp_auth_disabled", "false")
        if not isinstance(mcp_bypass, str) or mcp_bypass.lower() not in ("false", "0", "no", ""):
            raise ValueError("MCP authentication bypass is forbidden")
        operator_fields = {"operator_learning_coach_api_key", "operator_career_advisor_api_key"}
        if config.keys() & operator_fields and not operator_fields <= config.keys():
            raise ValueError("Both operator key references are required")
        key_fields = required | (operator_fields & config.keys())
        values = [config[name] for name in sorted(key_fields)]
        if any(not isinstance(v, str) or not v or not v.isascii() or v.strip() != v
               or any(ord(c) < 33 or ord(c) > 126 for c in v) for v in values):
            raise ValueError("Invalid specialist key configuration")
        if len(set(values)) != len(values):
            raise ValueError("Duplicate authentication keys")
        _legacy_schema()
        # The base class otherwise keeps a second plain-text config reference.
        super().__init__({})
        self._keys = ((config["api_key"], None),) + tuple(
            (config[i.name + "_api_key"], i) for i in SPECIALISTS)
        if operator_fields <= config.keys():
            self._keys += tuple((config["operator_" + i.name + "_api_key"],
                                 Identity("operator_" + i.name, i.bank, i.schema, False))
                                for i in SPECIALISTS)

    def identify(self, api_key: str | None) -> Identity | None:
        candidate = api_key.encode("utf-8") if isinstance(api_key, str) else b""
        found = False
        identity = None
        # Compare every configured key; no early-exit role/prefix oracle.
        for expected, principal in self._keys:
            matches = compare_digest(candidate, expected.encode("ascii"))
            if matches:
                found = True
                identity = principal
        if not found:
            raise AuthenticationError("Invalid authentication")
        return identity

    async def authenticate(self, context):
        # Never trust claims supplied by a caller or reused RequestContext.
        context.tenant_id = None
        context.api_key_id = None
        context.authenticated_schema = None
        identity = self.identify(context.api_key)
        schema = _legacy_schema()
        if identity is not None:
            from .ingress import _ADMITTED
            admitted = _ADMITTED.get()
            if admitted is None or admitted[0] is not self or admitted[1] != identity:
                raise AuthenticationError("Specialist access blocked: guarded ingress required")
            schema = identity.schema
            context.tenant_id = identity.name
        return TenantContext(schema_name=schema)

    async def list_tenants(self):
        return [Tenant(schema=_legacy_schema())] + [Tenant(schema=i.schema) for i in SPECIALISTS]

    async def get_allowed_config_fields(self, context, bank_id):
        return None if self.identify(context.api_key) is None else set()


# Explicit content-read allowlist. Profile/config/audit/admin reads are excluded.
SAFE_BANK_READS = frozenset({
    "get_chunk", "get_document", "get_document_history", "get_memory_unit",
    "get_observation_history", "list_document_chunks", "list_documents",
    "list_memory_units", "list_entities", "get_entity", "get_entity_graph",
    "get_entity_state", "list_tags", "list_mental_models", "get_mental_model_history",
    "list_mental_model_tags", "list_directives", "get_directive",
    "get_knowledge_base_tree", "get_knowledge_page", "search_knowledge_base",
})


class SpecialistOperationValidator(OperationValidatorExtension):
    """Defense in depth; does not confer ingress authority or provision schemas.

    This slot receives its own prefixed config: supply the same three key refs.
    Missing or mismatched keys reject rather than falling back to caller claims.
    """

    def __init__(self, config):
        super().__init__({})
        self._auth = SpecialistTenantExtension(config)

    def _identity(self, context):
        # Internal is set by trusted upstream worker construction, not by either
        # transport's JSON/header parser. A key-bearing context NEVER uses this
        # exception, even if internal=True or mcp_authenticated=True was supplied.
        if context.internal and context.api_key is None:
            from hindsight_api.schema_context import _current_schema
            if (context.tenant_id is None and context.api_key_id is None
                    and _current_schema.get() in {_legacy_schema(), *(i.schema for i in SPECIALISTS)}):
                return None
            raise AuthenticationError("Invalid internal authentication")
        return self._auth.identify(context.api_key)

    def _read(self, ctx):
        identity = self._identity(ctx.request_context)
        if identity is None or ctx.bank_id == identity.bank:
            return ValidationResult.accept()
        return ValidationResult.reject("Operation not permitted", status_code=403)

    async def _write(self, ctx):
        identity = self._identity(ctx.request_context)
        if identity is None or (not identity.read_only and ctx.bank_id == identity.bank):
            return ValidationResult.accept()
        return ValidationResult.reject("Operation not permitted", status_code=403)

    async def validate_recall(self, ctx):
        return self._read(ctx)

    async def validate_bank_read(self, ctx):
        identity = self._identity(ctx.request_context)
        if identity is not None and ctx.operation not in SAFE_BANK_READS:
            # Native content handlers use the read-only profile helper to load
            # attachment metadata. This is NOT general profile-read authority:
            # require a live own-bank content admission from the same key map.
            from .ingress import _ADMITTED, _ContentReadScope
            admitted = _ADMITTED.get()
            if (ctx.operation == 'get_bank_profile' and admitted is not None
                    and len(admitted) == 3
                    and isinstance(admitted[0], SpecialistTenantExtension)
                    and admitted[0]._keys == self._auth._keys
                    and admitted[1] == identity and ctx.bank_id == identity.bank
                    and isinstance(admitted[2], _ContentReadScope) and admitted[2].active):
                return self._read(ctx)
            return ValidationResult.reject("Operation not permitted", status_code=403)
        return self._read(ctx)

    async def validate_mental_model_get(self, ctx):
        return self._read(ctx)

    async def precheck(self, ctx):
        identity = self._identity(ctx.request_context)
        if identity is None:
            return ValidationResult.accept()
        if ctx.operation == "recall":
            return self._read(ctx)
        if not identity.read_only and ctx.operation == "retain":
            return self._read(ctx)
        return ValidationResult.reject("Operation not permitted", status_code=403)

    validate_retain = _write
    validate_reflect = _write
    validate_consolidate = _write
    validate_bank_write = _write
    validate_create_bank = _write
    validate_import = _write
    validate_mental_model_refresh = _write
    validate_mental_model_candidate = _write
    validate_memory_update = _write

    async def resolve_write_tag_scope(self, ctx):
        identity = self._identity(ctx.request_context)
        return None if identity is None or not identity.read_only else []

    async def bank_list_scope(self, request_context):
        identity = self._identity(request_context)
        return BankListScope(bank_ids=None if identity is None else [identity.bank])

    async def filter_mcp_tools(self, bank_id, request_context, tools):
        identity = self._identity(request_context)
        if identity is None:
            return tools
        if bank_id != identity.bank:
            return frozenset()
        allowed = {"recall"} if identity.read_only else {"recall", "retain"}
        return frozenset(tools) & allowed

    async def filter_bank_list(self, ctx):
        identity = self._identity(ctx.request_context)
        return BankListResult(banks=ctx.banks if identity is None else [
            bank for bank in ctx.banks if bank.get("bank_id") == identity.bank])
