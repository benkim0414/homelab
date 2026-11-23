"""Packaging contract; engine construction is intercepted, never startup weakened.

Run in an environment with the package installed. No DB/provider calls or lifespan
startup are attempted here; backend/image acceptance belongs to isolated integration.
"""
import importlib
import importlib.util
from importlib.metadata import entry_points
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'hindsight/extensions/specialist-memory'
AVAILABLE = importlib.util.find_spec('hindsight_api') is not None


def environment():
    env = {'PATH': os.environ.get('PATH', ''), 'HINDSIGHT_API_DATABASE_SCHEMA': 'public'}
    for slot, cls in [('TENANT', 'SpecialistTenantExtension'),
                      ('OPERATION_VALIDATOR', 'SpecialistOperationValidator')]:
        env[f'HINDSIGHT_API_{slot}_EXTENSION'] = f'homelab_hindsight_specialists:{cls}'
        for name, value in [('API_KEY', 'packaging-legacy'),
                            ('LEARNING_COACH_API_KEY', 'packaging-learning'),
                            ('CAREER_ADVISOR_API_KEY', 'packaging-career')]:
            env[f'HINDSIGHT_API_{slot}_{name}'] = value
    return env


@unittest.skipUnless(AVAILABLE,'requires the installed Hindsight package environment')
class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_factory_preserves_defaults_and_outermost_admission(self):
        server = importlib.import_module('homelab_hindsight_specialists.server')
        from hindsight_api.api import create_app as upstream_factory
        from hindsight_api.config import get_config
        from homelab_hindsight_specialists.ingress import SpecialistBoundary
        from hindsight_api.models import RequestContext
        from hindsight_api.extensions.tenant import AuthenticationError
        import httpx

        def engine(**kwargs):
            memory = MagicMock()
            memory._tenant_extension = kwargs['tenant_extension']
            memory._operation_validator = kwargs['operation_validator']
            return memory

        with patch.dict(os.environ, environment(), clear=True):
            # Config parsing is real; isolate its process-global cached value.
            with patch('hindsight_api.config._config_cache', None), \
                    patch('hindsight_api.config.find_dotenv', return_value=''):
                from dataclasses import asdict
                from hindsight_api.config import _get_raw_config
                config = get_config()
                defaults = asdict(_get_raw_config())
                before = dict(os.environ)
                with patch('hindsight_api.MemoryEngine', side_effect=engine) as constructor:
                    with patch('hindsight_api.api.create_app', wraps=upstream_factory) as factory:
                        app = server.create_app()
                self.assertIsInstance(app, SpecialistBoundary)
                constructor.assert_called_once_with(
                    tenant_extension=app.tenant,
                    operation_validator=app.app.state.memory._operation_validator,
                    run_migrations=config.run_migrations_on_startup)
                factory.assert_called_once_with(
                    app.app.state.memory, http_api_enabled=True,
                    mcp_api_enabled=config.mcp_enabled, mcp_mount_path='/mcp',
                    initialize_memory=True)
                # No provider/model/worker/test-mode overrides injected by our factory.
                self.assertEqual(asdict(_get_raw_config()), defaults)
                self.assertEqual({k: v for k, v in os.environ.items()
                                  if k.startswith('HINDSIGHT_')},
                                 {k: v for k, v in before.items()
                                  if k.startswith('HINDSIGHT_')})
                self.assertTrue(config.worker_enabled)
                self.assertIsNotNone(app.app.router.lifespan_context)
                with self.assertRaises(AuthenticationError):
                    await app.tenant.authenticate(RequestContext(api_key='packaging-learning'))
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url='http://packaging.invalid') as client:
                    response = await client.post('/v1/default/banks/next-level/memories/recall',
                        headers={'Authorization': 'Bearer packaging-learning'}, json={'query': 'test'})
                self.assertEqual(response.status_code, 403)
                app.app.state.memory.recall.assert_not_called()


@unittest.skipUnless(AVAILABLE,'requires the installed Hindsight package environment')
class EntrypointTests(unittest.TestCase):
    def test_installed_console_entrypoint_help_without_engine(self):
        scripts = list(entry_points(group='console_scripts', name='hindsight-specialist-api'))
        self.assertEqual(len(scripts), 1, 'production console script must be installed')
        self.assertEqual(scripts[0].value, 'homelab_hindsight_specialists.server:main')
        result = subprocess.run([str(Path(sys.executable).parent / 'hindsight-specialist-api'), '--help'],
                                cwd=ROOT / 'verification/cache/isolated-home',
                                env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                                     'HOME': str(ROOT / 'verification/cache/isolated-home')},
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Hindsight specialist', result.stdout)

    def test_cli_uses_guarded_factory_in_every_worker_and_upstream_server_defaults(self):
        server = importlib.import_module('homelab_hindsight_specialists.server')
        from hindsight_api.config import DEFAULT_HOST, get_config
        with patch.dict(os.environ, environment(), clear=True), \
                patch('hindsight_api.config._config_cache', None), \
                patch('hindsight_api.config.find_dotenv', return_value=''), \
                patch.object(sys, 'argv', ['hindsight-specialist-api']), \
                patch('uvicorn.run') as run:
            config = get_config()
            server.main()
            options = run.call_args.kwargs
            self.assertEqual(run.call_args.args, ('homelab_hindsight_specialists.server:create_app',))
            self.assertTrue(options['factory'])
            self.assertEqual(options['host'], config.host or DEFAULT_HOST)
            for field in ('port', 'workers', 'log_level', 'access_log'):
                self.assertEqual(options[field], getattr(config, field))
            self.assertEqual(options['timeout_keep_alive'], 30)
            self.assertEqual(options['timeout_graceful_shutdown'], 5)
            self.assertEqual(options['ws'], 'wsproto')
            self.assertFalse(options['proxy_headers'])


class DockerContractTests(unittest.TestCase):
    def test_pinned_native_image_and_allowlisted_context(self):
        dockerfile = PACKAGE / 'Dockerfile'
        self.assertTrue(dockerfile.is_file(), 'production Dockerfile is missing')
        text = '\n'.join(line for line in dockerfile.read_text().splitlines()
                         if not line.lstrip().startswith('#'))
        self.assertIn('FROM ghcr.io/vectorize-io/hindsight-api:1.2.1@sha256:'
                      '662109ece429871a81e036427fb93fbb09ba9dc4b01d320d356f114c0e1aedd8', text)
        self.assertIn('uv pip install --python /app/api/.venv/bin/python', text)
        self.assertNotIn('--no-deps', text)
        self.assertIn('uv pip check --python /app/api/.venv/bin/python', text)
        self.assertIn('USER hindsight', text)
        self.assertIn('CMD ["/app/api/.venv/bin/hindsight-specialist-api"]', text)
        self.assertNotIn('COPY .', text)
        self.assertNotIn('PYTHONPATH', text)
        import tomllib
        metadata = tomllib.loads((PACKAGE / 'pyproject.toml').read_text())
        self.assertEqual(metadata['project']['dependencies'],
                         ['hindsight-api-slim==1.2.1', 'mcp==2.3.0'])
        rules = [line for line in (PACKAGE / '.dockerignore').read_text().splitlines()
                 if line and not line.startswith('#')]
        self.assertEqual(rules, ['**', '!pyproject.toml', '!src/',
            '!src/homelab_hindsight_specialists/',
            '!src/homelab_hindsight_specialists/__init__.py',
            '!src/homelab_hindsight_specialists/ingress.py',
            '!src/homelab_hindsight_specialists/server.py'])


if __name__ == '__main__':
    unittest.main()
