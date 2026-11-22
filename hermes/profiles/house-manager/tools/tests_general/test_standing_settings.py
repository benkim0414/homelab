"""Explicit opt-in and fail-closed standing-permission configuration."""
import unittest
from custom_components.house_manager_general.native import validate_settings
from custom_components.house_manager_general.engine import ApprovalError


class StandingSettingsTests(unittest.TestCase):
    def settings(self):
        return {'bot_user_id':'b'*32, 'discord_token':'FAKE',
                'discord_channel_id':'33', 'discord_user_id':'22'}

    def test_legacy_configuration_remains_opt_out(self):
        self.assertNotIn('standing_permissions', validate_settings(self.settings()))

    def test_explicit_boolean_only_and_separate_approver_preserved(self):
        for enabled in (False, True):
            value = dict(self.settings(), standing_permissions=enabled,
                         chat_approver_user_id='c'*32)
            checked = validate_settings(value)
            self.assertIs(checked['standing_permissions'], enabled)
            self.assertEqual(checked['chat_approver_user_id'], 'c'*32)
            self.assertIsNot(checked, value)
        for invalid in (None, 'true', 'false', 0, 1, [], {}):
            with self.subTest(invalid=invalid), self.assertRaises(ApprovalError):
                validate_settings(dict(self.settings(), standing_permissions=invalid))

    def test_unknown_permission_settings_are_not_accepted(self):
        with self.assertRaises(ApprovalError):
            validate_settings(dict(self.settings(), unrestricted_admin=True))
