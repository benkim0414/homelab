"""PVC installer configuration insertion is validated before any writes."""
import unittest
import hashlib
from types import SimpleNamespace
from unittest.mock import patch
import yaml
import install_standing_source as installer


class InstallerTests(unittest.TestCase):
    def setUp(self):
        scope={}
        exec(installer.SETTING_HELPER,scope)
        self.enable=scope['enable_standing']

    def test_flow_and_block_mapping_preserve_original_values(self):
        for source in ('{"bot_user_id":"example","discord_token":"placeholder"}\n',
                       'bot_user_id: example\ndiscord_token: !secret discord\n',
                       '---\nbot_user_id: example\n...\n'):
            with self.subTest(source=source):
                original=yaml.compose(source)
                result=yaml.compose(self.enable(source))
                self.assertEqual([(k.value,v.tag,v.value) for k,v in result.value[:-1]],
                                 [(k.value,v.tag,v.value) for k,v in original.value])
                self.assertEqual((result.value[-1][0].value,result.value[-1][1].tag,result.value[-1][1].value),
                                 ('standing_permissions','tag:yaml.org,2002:bool','true'))
                self.assertEqual(result.flow_style,original.flow_style)

    def test_duplicate_or_nonmapping_settings_fail_before_write(self):
        for source in ('standing_permissions: false\n','[one,two]','plain scalar'):
            with self.subTest(source=source),self.assertRaises(AssertionError):
                self.enable(source)

    def test_embedded_installers_compile(self):
        compile(installer.REMOTE_HA,'remote-ha','exec')
        compile(installer.REMOTE_PROFILE,'remote-profile','exec')

    def test_baseline_is_pinned_across_publication(self):
        path=installer.COMPONENT/'engine.py'
        with patch.object(installer.subprocess,'run',return_value=SimpleNamespace(stdout=b'original source')) as run:
            self.assertEqual(installer.git_baseline(path),hashlib.sha256(b'original source').hexdigest())
        run.assert_called_once_with(['git','show',installer.BASELINE_REF+':'+str(path.relative_to(installer.ROOT))],
                                    cwd=installer.ROOT,check=True,capture_output=True)
        self.assertEqual(installer.BASELINE_REF,'074c76df1dafed3ca3b42086a76ea0cab7554343')
