"""Synthetic-only tests; run with hindsight-api-slim==1.2.1 installed."""
import importlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hindsight/extensions/specialist-memory/src"))


class PackageTests(unittest.TestCase):
    def test_extension_package_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("homelab_hindsight_specialists"),
                             "local specialist extension is missing")


def synthetic_config():
    # Not credentials: opaque, synthetic test values only.
    return {"api_key": "synthetic-legacy-" + "a" * 32,
            "learning_coach_api_key": "synthetic-learning-" + "b" * 32,
            "career_advisor_api_key": "synthetic-career-" + "c" * 32}


@unittest.skipUnless(importlib.util.find_spec("hindsight_api"), "requires real hindsight-api-slim==1.2.1")
class TenantFixture:
    def setUp(self):
        self.module = importlib.import_module("homelab_hindsight_specialists")
        self.assertTrue(hasattr(self.module, "SpecialistTenantExtension"),
                        "tenant policy implementation is missing")
        from hindsight_api.models import RequestContext
        from hindsight_api.extensions.tenant import AuthenticationError
        self.Context = RequestContext
        self.AuthError = AuthenticationError
        self.config = synthetic_config()
        self.schema = patch.object(self.module, "get_config",
                                   return_value=SimpleNamespace(database_schema="public"))
        self.schema.start()
        self.addCleanup(self.schema.stop)
        self.tenant = self.module.SpecialistTenantExtension(self.config)


class TenantTests(TenantFixture, unittest.IsolatedAsyncioTestCase):
    async def test_legacy_schema_and_unrestricted_config_are_preserved(self):
        ctx = self.Context(api_key=self.config["api_key"], tenant_id="forged", api_key_id="forged")
        self.assertEqual((await self.tenant.authenticate(ctx)).schema_name, "public")
        self.assertIsNone(ctx.tenant_id)
        self.assertIsNone(ctx.api_key_id)
        self.assertIsNone(await self.tenant.get_allowed_config_fields(ctx, "reserve-bank"))

    async def test_worker_tenants_include_legacy_and_fixed_specialists(self):
        self.assertEqual([t.schema for t in await self.tenant.list_tenants()],
                         ["public", "user_learning_coach", "user_career_advisor"])

    async def test_specialists_blocked_on_both_transports_without_guarded_ingress(self):
        for name in ("learning_coach", "career_advisor"):
            for auth in (self.tenant.authenticate, self.tenant.authenticate_mcp):
                ctx = self.Context(api_key=self.config[name + "_api_key"], tenant_id="legacy")
                with self.assertRaisesRegex(self.AuthError, "guarded ingress"):
                    await auth(ctx)
                self.assertIsNone(ctx.tenant_id)
                self.assertIsNone(ctx.api_key_id)
                self.assertEqual(await self.tenant.get_allowed_config_fields(ctx, "any"), set())

    async def test_unknown_missing_and_unicode_keys_fail_without_disclosure(self):
        for key in (None, "synthetic-unknown", "\N{SNOWMAN}"):
            with self.assertRaises(self.AuthError) as caught:
                await self.tenant.authenticate(self.Context(api_key=key, internal=True,
                                                          mcp_authenticated=True, tenant_id="legacy"))
            self.assertNotIn(str(key), str(caught.exception))

    async def test_legacy_tracks_current_configured_schema(self):
        with patch.object(self.module, "get_config", return_value=SimpleNamespace(database_schema="legacy_schema")):
            self.assertEqual((await self.tenant.authenticate(self.Context(api_key=self.config["api_key"]))).schema_name,
                             "legacy_schema")
            self.assertEqual((await self.tenant.list_tenants())[0].schema, "legacy_schema")

    def test_missing_malformed_duplicate_and_unknown_config_fail_closed(self):
        cases = [{}, {**self.config, "mcp_auth_disabled": "true"},
                 {**self.config, "surprise": "value"},
                 {**self.config, "mcp_auth_disabled": None},
                 {**self.config, "career_advisor_api_key": self.config["api_key"]},
                 {**self.config, "learning_coach_api_key": " "},
                 {**self.config, "learning_coach_api_key": "\N{SNOWMAN}"}]
        for name in self.config:
            cases.append({k: v for k, v in self.config.items() if k != name})
        for config in cases:
            with self.subTest(fields=sorted(config)):
                with self.assertRaises(ValueError) as caught:
                    self.module.SpecialistTenantExtension(config)
                for secret in self.config.values():
                    self.assertNotIn(secret, str(caught.exception))

    def test_schema_collision_and_invalid_schema_fail_closed(self):
        for schema in ("user_learning_coach", "user_career_advisor", "bad;schema", "pg_catalog", "", "x" * 64):
            with patch.object(self.module, "get_config", return_value=SimpleNamespace(database_schema=schema)):
                with self.assertRaises(ValueError):
                    self.module.SpecialistTenantExtension(self.config)

    def test_legacy_mcp_transport_override_is_rejected_without_reading_it(self):
        import os
        with patch.dict(os.environ, {"HINDSIGHT_API_MCP_AUTH_TOKEN": "synthetic-override"}):
            with self.assertRaisesRegex(ValueError, "MCP"):
                self.module.SpecialistTenantExtension(self.config)


class PolicyFixture(TenantFixture):
    def setUp(self):
        super().setUp()
        self.assertTrue(hasattr(self.module, "SpecialistOperationValidator"),
                        "operation policy implementation is missing")
        self.policy = self.module.SpecialistOperationValidator(self.config)
        from hindsight_api.extensions import operation_validator as types
        self.types = types

    def context(self, role="learning_coach", **claims):
        return self.Context(api_key=self.config[(role + "_api_key") if role != "legacy" else "api_key"], **claims)


class PolicyTests(PolicyFixture, unittest.IsolatedAsyncioTestCase):
    async def test_only_own_bank_recall_accepted_and_spoofed_claims_ignored(self):
        for identity in self.module.SPECIALISTS:
            for bank in (identity.bank, "reserve-bank", "house-rules", "other", ""):
                result = await self.policy.validate_recall(self.types.RecallContext(
                    bank_id=bank, query="synthetic", request_context=self.context(identity.name, tenant_id="legacy",
                                                                                 api_key_id="legacy")))
                self.assertEqual(result.allowed, bank == identity.bank)

    async def test_every_write_and_generation_hook_rejects_specialists(self):
        hooks = ("validate_retain", "validate_reflect", "validate_consolidate", "validate_bank_write",
                 "validate_create_bank", "validate_import", "validate_mental_model_refresh",
                 "validate_mental_model_candidate", "validate_memory_update")
        for name in hooks:
            # Each hook only reads these common fields; actual upstream context
            # type compatibility is exercised separately below.
            ctx = SimpleNamespace(bank_id="infinite-recursion", request_context=self.context())
            with self.subTest(hook=name):
                self.assertFalse((await getattr(self.policy, name)(ctx)).allowed)
                ctx.request_context = self.context("legacy")
                self.assertTrue((await getattr(self.policy, name)(ctx)).allowed)

    async def test_bank_read_allowlist_denies_admin_config_unknown_and_other_banks(self):
        for operation in list(self.types.BankReadOperation) + ["future_read"]:
            ctx = self.types.BankReadContext("infinite-recursion", operation, self.context())
            result = await self.policy.validate_bank_read(ctx)
            self.assertEqual(result.allowed, operation in self.module.SAFE_BANK_READS)
            ctx.bank_id = "reserve-bank"
            self.assertFalse((await self.policy.validate_bank_read(ctx)).allowed)

    async def test_precheck_allows_only_own_recall(self):
        for operation in ("recall", "retain", "reflect", "future_operation"):
            ctx = self.types.PrecheckContext(operation=operation, bank_id="infinite-recursion",
                                             request_context=self.context())
            self.assertEqual((await self.policy.precheck(ctx)).allowed, operation == "recall")

    async def test_write_scope_blocks_indirect_export_and_file_retain_paths(self):
        ctx = self.types.TagScopeContext("infinite-recursion", self.context())
        self.assertEqual(await self.policy.resolve_write_tag_scope(ctx), [])
        ctx.request_context = self.context("legacy")
        self.assertIsNone(await self.policy.resolve_write_tag_scope(ctx))

    async def test_list_scope_never_reads_other_banks(self):
        result = await self.policy.bank_list_scope(self.context())
        self.assertEqual(result.bank_ids, ["infinite-recursion"])
        result = await self.policy.filter_bank_list(self.types.BankListContext(
            banks=[{"bank_id": "reserve-bank"}, {"bank_id": "infinite-recursion"}], request_context=self.context()))
        self.assertEqual(result.banks, [{"bank_id": "infinite-recursion"}])

    async def test_unknown_external_identity_denied_even_when_claiming_internal(self):
        for claims in ({"tenant_id": "legacy"}, {"internal": True}, {"mcp_authenticated": True}):
            ctx = self.types.RecallContext("infinite-recursion", "synthetic", self.Context(api_key="synthetic-wrong", **claims))
            with self.assertRaises(self.AuthError):
                await self.policy.validate_recall(ctx)

    async def test_worker_no_key_requires_internal_and_allowlisted_schema(self):
        from hindsight_api import schema_context as config
        for schema in ("public", "user_learning_coach", "user_career_advisor", "unrecognized"):
            token = config._current_schema.set(schema)
            try:
                ctx = self.types.ConsolidateContext("infinite-recursion", self.Context(internal=True))
                if schema == "unrecognized":
                    with self.assertRaises(self.AuthError):
                        await self.policy.validate_consolidate(ctx)
                else:
                    self.assertTrue((await self.policy.validate_consolidate(ctx)).allowed)
            finally:
                config._current_schema.reset(token)
        with self.assertRaises(self.AuthError):
            await self.policy.validate_consolidate(self.types.ConsolidateContext("any", self.Context()))


class UpstreamCompatibilityTests(PolicyFixture, unittest.IsolatedAsyncioTestCase):

    async def test_exact_upstream_version_and_hook_interfaces(self):
        from importlib.metadata import version
        import inspect
        from hindsight_api.extensions.operation_validator import OperationValidatorExtension
        self.assertEqual(version("hindsight-api-slim"), "1.2.1")
        for name in ("precheck", "validate_retain", "validate_recall", "validate_reflect",
                     "validate_consolidate", "validate_bank_read", "validate_bank_write",
                     "validate_create_bank", "validate_import", "validate_mental_model_get",
                     "validate_mental_model_refresh", "validate_mental_model_candidate",
                     "validate_memory_update", "resolve_write_tag_scope", "bank_list_scope"):
            self.assertTrue(inspect.iscoroutinefunction(getattr(OperationValidatorExtension, name)))
            self.assertEqual(len(inspect.signature(getattr(type(self.policy), name)).parameters), 2)

    async def test_real_loader_uses_actual_base_classes_and_synthetic_env(self):
        import os
        from hindsight_api.extensions.loader import load_extension
        from hindsight_api.extensions.tenant import TenantExtension
        from hindsight_api.extensions.operation_validator import OperationValidatorExtension
        for prefix, cls, base_type in (("TENANT", "SpecialistTenantExtension", TenantExtension),
                                       ("OPERATION_VALIDATOR", "SpecialistOperationValidator", OperationValidatorExtension)):
            env = {"HINDSIGHT_API_" + prefix + "_" + k.upper(): v for k, v in self.config.items()}
            env["HINDSIGHT_API_" + prefix + "_EXTENSION"] = "homelab_hindsight_specialists:" + cls
            with patch.dict(os.environ, env, clear=True):
                loaded = load_extension(prefix, base_type)
            self.assertIsInstance(loaded, base_type)

    async def test_real_engine_export_gates_reject_before_backend_access(self):
        from hindsight_api.engine.memory_engine import MemoryEngine
        from hindsight_api.extensions.operation_validator import OperationValidationError
        from unittest.mock import AsyncMock
        # Do not construct the engine: its constructor configures real providers.
        # Execute actual upstream methods against a synthetic, uninitialized
        # engine; backend sentinel proves these gates run before DB/storage.
        engine = object.__new__(MemoryEngine)
        engine._tenant_extension = self.tenant
        engine._operation_validator = self.policy
        engine._get_backend = AsyncMock(side_effect=AssertionError("backend must not be reached"))
        ctx = self.context()
        # Trusted synthetic engine fixture ONLY: production transports cannot set
        # this field. This isolates indirect policy enforcement from blocked auth.
        ctx.authenticated_schema = "user_learning_coach"
        for method in (engine.submit_export_documents_async, engine.submit_bank_export_async):
            with self.assertRaises(OperationValidationError):
                await method("infinite-recursion", ctx)
        engine._get_backend.assert_not_called()

    async def test_real_engine_legacy_auth_and_specialist_block(self):
        from hindsight_api.engine.memory_engine import MemoryEngine
        from hindsight_api.schema_context import _current_schema
        engine = object.__new__(MemoryEngine)
        engine._tenant_extension = self.tenant
        token = _current_schema.set(None)
        try:
            self.assertEqual(await engine._authenticate_tenant(self.context("legacy")), "public")
            with self.assertRaises(self.AuthError):
                await engine._authenticate_tenant(self.context())
        finally:
            _current_schema.reset(token)

    async def test_real_http_bank_routes_block_specialists_before_backend(self):
        import httpx
        from hindsight_api.engine.memory_engine import MemoryEngine
        from hindsight_api.api.http import create_app
        from unittest.mock import AsyncMock
        engine = object.__new__(MemoryEngine)
        engine._tenant_extension = self.tenant
        engine._operation_validator = self.policy
        engine._audit_logger = None
        engine._get_backend = AsyncMock(side_effect=AssertionError("backend must not be reached"))
        app = create_app(engine, initialize_memory=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic.invalid") as client:
            for method, suffix, body in (("POST", "/memories/recall", {"query": "synthetic"}),
                                         ("POST", "/memories", {"items": [{"content": "synthetic"}]}),
                                         ("DELETE", "", None),
                                         ("GET", "/audit-logs", None)):
                response = await client.request(method, "/v1/default/banks/infinite-recursion" + suffix,
                    headers={"Authorization": "Bearer " + self.config["learning_coach_api_key"]}, json=body)
                self.assertEqual(response.status_code, 401, response.text)
        engine._get_backend.assert_not_called()

    async def test_real_mcp_auth_rejects_session_reuse_and_missing_headers(self):
        import httpx
        from hindsight_api.api import mcp
        from unittest.mock import AsyncMock
        # Prebuilt downstream sentinel apps avoid constructing real providers or
        # opening a network port. The actual upstream MCP middleware handles auth.
        downstream = AsyncMock(side_effect=AssertionError("MCP app must not be reached"))
        memory = SimpleNamespace(_tenant_extension=self.tenant)
        with patch.object(mcp, "MCP_AUTH_TOKEN", None):
            app = mcp.MCPMiddleware(downstream, memory, multi_bank_app=downstream,
                single_bank_app=downstream, multi_bank_server=object(), single_bank_server=object())
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic.invalid") as client:
                for headers in ({}, {"Mcp-Session-Id": "synthetic-old-session"},
                                {"Authorization": "Bearer " + self.config["learning_coach_api_key"]},
                                {"Authorization": "Bearer " + self.config["learning_coach_api_key"],
                                 "Mcp-Session-Id": "synthetic-old-session"}):
                    response = await client.post("/mcp/infinite-recursion", headers=headers,
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "retain", "arguments": {"content": "synthetic"}}})
                    self.assertEqual(response.status_code, 401)
        downstream.assert_not_called()


if __name__ == "__main__":
    unittest.main()
