import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

SOURCE = Path(__file__).resolve().parents[1] / 'bootstrap.py'
spec = importlib.util.spec_from_file_location('verification_bootstrap', SOURCE)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class DownloadTests(unittest.TestCase):
    def test_release_cdn_504_falls_back_to_same_official_asset(self):
        url = 'https://github.com/owner/project/releases/download/v1.2.3/tool.tar.gz'
        replies = [HTTPError(url, 504, 'Gateway Timeout', {}, None),
                   io.BytesIO(b'{"assets":[{"name":"tool.tar.gz","id":123}]}'),
                   io.BytesIO(b'checked by caller')]
        with patch.object(bootstrap.urllib.request, 'urlopen', side_effect=replies) as get:
            self.assertEqual(bootstrap.download(url), b'checked by caller')
            self.assertEqual(get.call_args_list[1].args[0],
                             'https://api.github.com/repos/owner/project/releases/tags/v1.2.3')
            request = get.call_args_list[2].args[0]
            self.assertEqual(request.full_url,
                             'https://api.github.com/repos/owner/project/releases/assets/123')
            self.assertEqual(request.get_header('Accept'), 'application/octet-stream')

    def test_404_and_non_github_fail_without_fallback(self):
        for url, code in [('https://github.com/o/r/releases/download/v1/file', 404),
                          ('https://get.helm.sh/file', 504)]:
            with self.subTest(url=url, code=code):
                error = HTTPError(url, code, 'failure', {}, None)
                with patch.object(bootstrap.urllib.request, 'urlopen', side_effect=error) as get:
                    with self.assertRaises(HTTPError):
                        bootstrap.download(url)
                    self.assertEqual(get.call_count, 1)

    def test_ambiguous_api_asset_fails_closed(self):
        url = 'https://github.com/o/r/releases/download/v1/file'
        with patch.object(bootstrap.urllib.request, 'urlopen', side_effect=[
                HTTPError(url, 504, 'failure', {}, None), io.BytesIO(b'{"assets":[]}')]):
            with self.assertRaisesRegex(RuntimeError, 'missing or ambiguous'):
                bootstrap.download(url)


if __name__ == '__main__':
    unittest.main()
