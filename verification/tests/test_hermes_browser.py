"""Exercise the CDP bridge without launching a browser or contacting websites.

The aiohttp cases also run inside the deployed image, which supplies aiohttp.
"""
import asyncio
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get('HERMES_BROWSER_SOURCE', ROOT / 'hermes/browser-server.py'))
try:
    import aiohttp
    from aiohttp.test_utils import TestClient, TestServer
except ImportError:
    aiohttp = None


@unittest.skipUnless(yaml, 'manifest check uses the local verifier environment')
class BrowserManifestTests(unittest.TestCase):
    def test_embedded_source_and_rollout_checksums_match(self):
        source = SOURCE.read_bytes()
        cm = yaml.safe_load((ROOT / 'hermes/browser-configmap.yaml').read_text())
        self.assertEqual(cm['data']['browser-server.py'], source.decode())
        deployment = next(yaml.safe_load_all((ROOT / 'hermes/browser.yaml').read_text()))
        annotations = deployment['spec']['template']['metadata']['annotations']
        self.assertEqual(annotations['checksum/server'], hashlib.sha256(source).hexdigest())
        profile = (ROOT / 'k3s-ansible/files/hermes-browser-amd64.json').read_bytes()
        self.assertEqual(annotations['checksum/seccomp'], hashlib.sha256(profile).hexdigest())


@unittest.skipUnless(aiohttp, 'aiohttp integration cases run in the browser image')
class BrowserBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        spec = importlib.util.spec_from_file_location('browser_bridge', SOURCE)
        self.bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bridge)

    async def test_stop_removes_profile_even_if_process_already_exited(self):
        with tempfile.TemporaryDirectory() as root:
            profile = Path(root) / 'profile'
            profile.mkdir()
            (profile / 'cookie').write_text('test cookie')
            browser = self.bridge.Browser()
            browser.profile = str(profile)
            browser.process = AsyncMock(returncode=0)
            browser.ws_url = 'stale'
            with patch.object(self.bridge.os, 'killpg') as kill_group:
                await browser.stop()
            kill_group.assert_called_once()
            self.assertFalse(profile.exists())
            self.assertIsNone(browser.ws_url)

    async def test_stop_reaps_adopted_children_after_waiting_for_browser(self):
        browser = self.bridge.Browser()
        process = browser.process = AsyncMock(returncode=None)
        calls = []
        process.wait.side_effect = lambda: calls.append('wait')

        def reap(*_):
            calls.append('reap')
            raise ChildProcessError()

        with patch.object(self.bridge.os, 'killpg'), patch.object(self.bridge.os, 'waitpid', reap):
            await browser.stop()
        self.assertEqual(calls, ['wait', 'reap'])

    async def test_discovery_rewrites_host_and_health_does_not_refresh_lease(self):
        async def upstream_version(request):
            return aiohttp.web.json_response({'webSocketDebuggerUrl': 'ws://127.0.0.1:9223/private'})

        upstream = aiohttp.web.Application()
        upstream.router.add_get('/json/version', upstream_version)
        async with TestServer(upstream) as server:
            app = self.bridge.make_app()
            app.cleanup_ctx.clear()
            browser = self.bridge.Browser()
            browser.start = AsyncMock()
            browser.last_used = 123
            app['browser'] = browser
            async with aiohttp.ClientSession() as session:
                app['client'] = session
                with patch.object(self.bridge, 'LOCAL_ROOT', str(server.make_url('')).rstrip('/')):
                    async with TestClient(TestServer(app)) as client:
                        response = await client.get('/healthz')
                        self.assertEqual(response.status, 200)
                        self.assertEqual(browser.last_used, 123)
                        response = await client.get('/json/version', headers={'Host': 'attacker.invalid'})
                        payload = await response.json()
                        self.assertEqual(payload['webSocketDebuggerUrl'],
                                         'ws://hermes-browser.hermes.svc.cluster.local:9222/devtools/browser')
                        response = await client.get('/arbitrary-proxy-path')
                        self.assertEqual(response.status, 404)
                        response = await client.get('/devtools/browser',
                                                    headers={'Origin': 'https://untrusted.example'})
                        self.assertEqual(response.status, 403)
                        response = await client.get('/json/version', headers={'Origin': 'null'})
                        self.assertEqual(response.status, 403)

    async def test_idle_reaper_stops_browser_and_shutdown_closes_it(self):
        browser = self.bridge.Browser()
        browser.last_used = 0
        browser.start = AsyncMock()
        browser.stop = AsyncMock()
        stopped = asyncio.Event()
        browser.stop.side_effect = stopped.set
        real_sleep = asyncio.sleep

        async def fast_sleep(_):
            await real_sleep(.01)

        with patch.object(self.bridge, 'Browser', return_value=browser), \
                patch.object(self.bridge.asyncio, 'sleep', fast_sleep):
            ctx = self.bridge.lifecycle({})
            await anext(ctx)
            await asyncio.wait_for(stopped.wait(), 1)
            await ctx.aclose()
        self.assertGreaterEqual(browser.stop.await_count, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
