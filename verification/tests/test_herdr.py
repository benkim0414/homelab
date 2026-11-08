import importlib.util
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "hermes/herdr/hermes-cluster.py"
spec = importlib.util.spec_from_file_location("hermes_cluster", SOURCE)
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


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


if __name__ == "__main__":
    unittest.main()
