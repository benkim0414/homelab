import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "herdr/image/hermes.py"
spec = importlib.util.spec_from_file_location("hermes_cluster", SOURCE)
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)

OPENCLAW = ROOT / "herdr/image/openclaw.py"
openclaw_spec = importlib.util.spec_from_file_location("openclaw_cluster", OPENCLAW)
openclaw = importlib.util.module_from_spec(openclaw_spec)
openclaw_spec.loader.exec_module(openclaw)


def pod(name="hermes-current", ready=True, deleting=False, app="hermes"):
    return {"metadata": {"name": name, "labels": {"app": app},
                         **({"deletionTimestamp": "now"} if deleting else {})},
            "status": {"phase": "Running", "conditions": [
                {"type": "Ready", "status": "True" if ready else "False"}]}}


class WrapperTests(unittest.TestCase):
    def test_ready_pod_excludes_old_terminating_and_other_apps(self):
        items = [pod("old", deleting=True), pod("unready", ready=False),
                 pod("browser", app="hermes-browser"), pod()]
        self.assertEqual(wrapper.select_pod(items), "hermes-current")

    def test_no_pod_does_not_start_an_agent(self):
        with self.assertRaisesRegex(ValueError, "found 0"):
            wrapper.select_pod([pod(ready=False)])

    def test_multiple_ready_pods_does_not_choose_arbitrarily(self):
        with self.assertRaisesRegex(ValueError, "found 2"):
            wrapper.select_pod([pod("one"), pod("two")])

    def test_exec_drops_to_hermes_and_uses_existing_home(self):
        command = wrapper.exec_command("target")
        self.assertIn("/command/s6-setuidgid", command)
        self.assertEqual(command[command.index("-c") + 1], "hermes")
        self.assertIn("HOME=/opt/data", command)
        self.assertIn("HERMES_HOME=/opt/data", command)
        self.assertNotIn("--resume", command)

    def test_session_is_an_argument_not_interpolated_into_shell(self):
        session = "test;$(touch /tmp/should-not-exist)"
        command = wrapper.exec_command("target", session)
        self.assertEqual(command[-2:], ["--resume", session])
        self.assertNotIn(session, command[command.index("/bin/sh") + 2])

    def test_noninteractive_launch_fails_before_kubernetes_access(self):
        result = subprocess.run(["python3", "-B", str(SOURCE)], input="", text=True,
                                capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("interactive Herdr terminal", result.stderr)

    def test_invalid_resume_rejected_before_kubernetes_access(self):
        for session in ("", "-bad", "two words"):
            with self.subTest(session=session):
                result = subprocess.run(["python3", "-B", str(SOURCE), "--resume=" + session],
                                        input="", text=True, capture_output=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("SESSION_ID must", result.stderr)


class OpenClawTests(unittest.TestCase):
    def test_selects_only_ready_openclaw_without_terminating_pods(self):
        items = [pod("old", deleting=True, app="openclaw"),
                 pod("unready", ready=False, app="openclaw"), pod(),
                 pod("current", app="openclaw")]
        self.assertEqual(openclaw.select_pod(items), "current")

    def test_zero_and_multiple_ready_pods_fail(self):
        for items in ([], [pod("one", app="openclaw"), pod("two", app="openclaw")]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                openclaw.select_pod(items)

    def test_command_uses_gateway_and_existing_workspace(self):
        command = openclaw.exec_command("current")
        self.assertEqual(command[command.index("-n") + 1], "openclaw")
        self.assertEqual(command[command.index("-c") + 1], "gateway")
        self.assertIn("cd /home/node/.openclaw/workspace", command[-3])
        self.assertIn("openclaw tui --session", command[-3])
        self.assertEqual(command[-1], "herdr")
        self.assertNotIn("--local", command)
        self.assertNotIn("--token", command)

    def test_session_is_literal_not_shell_code(self):
        name = 'task;$(touch${IFS}/tmp/should-not-exist)'
        command = openclaw.exec_command("current", name)
        self.assertEqual(command[-1], name)
        self.assertNotIn(name, command[-3])

    def test_invalid_names_and_noninteractive_launch_fail_before_api_access(self):
        for name in ("", "-bad", "two words", "control\x1b"):
            with self.subTest(name=name):
                result = subprocess.run(["python3", "-B", str(OPENCLAW), "--session=" + name],
                                        input="", text=True, capture_output=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("NAME must", result.stderr)
        result = subprocess.run(["python3", "-B", str(OPENCLAW)],
                                input="", text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("interactive Herdr terminal", result.stderr)

    def test_launcher_passes_session_and_removes_inherited_agent_hint(self):
        import json
        response = subprocess.CompletedProcess([], 0, json.dumps({
            "items": [pod("current", app="openclaw")]}), "")
        with patch.object(sys, "argv", [str(OPENCLAW), "--session", "homelab"]), \
                patch.object(sys.stdin, "isatty", return_value=True), \
                patch.object(sys.stdout, "isatty", return_value=True), \
                patch.object(openclaw.subprocess, "run", return_value=response) as discover, \
                patch.object(openclaw.os, "execvpe") as execute, \
                patch.dict(openclaw.os.environ, {"HERDR_AGENT": "hermes"}):
            openclaw.main()
        self.assertEqual(discover.call_count, 1)
        command = discover.call_args.args[0]
        self.assertEqual(command[command.index("-n") + 1], "openclaw")
        self.assertEqual(execute.call_args.args[1][-1], "homelab")
        self.assertNotIn("HERDR_AGENT", execute.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
