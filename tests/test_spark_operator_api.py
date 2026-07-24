from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "spark-operator-api.py"


def load_module(state: Path):
    os.environ["SPARK_OPERATOR_STATE"] = str(state)
    spec = importlib.util.spec_from_file_location("spark_operator_api_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OperatorApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.api = load_module(self.root / "state")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_action_validation_is_allowlisted_and_normalized(self) -> None:
        clean = self.api.validate_action(
            "benchmaster_add",
            {
                "type": "perf_sweep",
                "profile_id": "qwen-profile",
                "front": 1,
                "note": "test",
                "ignored": "never forwarded",
            },
        )
        self.assertEqual(
            clean,
            {
                "type": "perf_sweep",
                "profile_id": "qwen-profile",
                "front": True,
                "note": "test",
            },
        )
        with self.assertRaises(ValueError):
            self.api.validate_action("shell", {"command": "rm -rf /"})
        with self.assertRaises(ValueError):
            self.api.validate_action("inference_switch", {"profile": "../../etc/passwd"})

    def test_proposal_requires_confirmation_and_records_result(self) -> None:
        proposal = self.api.create_proposal(
            "inference_switch",
            {"profile": "golden-profile"},
            turn_id="turn-123",
            source="hermes",
        )
        self.assertEqual(proposal["state"], "pending")
        self.assertNotIn("created_epoch", proposal)
        with mock.patch.object(self.api, "execute_action", return_value={"ok": True}) as execute:
            resolved = self.api.confirm_proposal(proposal["id"])
        execute.assert_called_once_with("inference_switch", {"profile": "golden-profile"})
        self.assertEqual(resolved["state"], "succeeded")
        with self.assertRaises(RuntimeError):
            self.api.confirm_proposal(proposal["id"])

    def test_cancelled_proposal_never_executes(self) -> None:
        proposal = self.api.create_proposal("inference_stop", {})
        cancelled = self.api.cancel_proposal(proposal["id"])
        self.assertEqual(cancelled["state"], "cancelled")
        with self.assertRaises(RuntimeError):
            self.api.confirm_proposal(proposal["id"])

    def test_install_proposal_requires_install_token(self) -> None:
        token_path = self.root / "install-token"
        token_path.write_text("correct-token\n", encoding="utf-8")
        self.api.INSTALL_TOKEN_PATH = token_path
        proposal = self.api.create_proposal("install", {"target": "gateway", "args": []})
        with self.assertRaisesRegex(RuntimeError, "valid install token"):
            self.api.confirm_proposal(proposal["id"], "wrong-token")

    def test_goals_are_durable_and_validated(self) -> None:
        goal = self.api.upsert_goal({"title": "Keep recipes current", "status": "active"})
        updated = self.api.upsert_goal(
            {"title": goal["title"], "notes": "Weekly review", "status": "paused"},
            goal["id"],
        )
        self.assertEqual(updated["status"], "paused")
        self.assertEqual(self.api.load_goals()[0]["notes"], "Weekly review")
        self.api.delete_goal(goal["id"])
        self.assertEqual(self.api.load_goals(), [])
        with self.assertRaises(ValueError):
            self.api.upsert_goal({"title": "", "status": "active"})

    def test_agent_goal_proposal_updates_durable_goals(self) -> None:
        proposal = self.api.create_proposal(
            "goal_save",
            {"title": "Watch benchmark drift", "notes": "Report weekly", "status": "active"},
            source="hermes",
        )
        resolved = self.api.confirm_proposal(proposal["id"])
        self.assertEqual(resolved["state"], "succeeded")
        self.assertEqual(self.api.load_goals()[0]["title"], "Watch benchmark drift")

    def test_provider_settings_are_redacted(self) -> None:
        data = self.root / "hermes"
        data.mkdir()
        (data / "config.yaml").write_text(
            "model:\n  provider: openrouter\n  default: model/name\n",
            encoding="utf-8",
        )
        (data / ".env").write_text("OPENROUTER_API_KEY=secret-value\n", encoding="utf-8")
        self.api.HERMES_DATA = data
        settings = self.api.provider_settings()
        self.assertTrue(settings["api_key_configured"])
        self.assertNotIn("secret-value", str(settings))
        self.assertNotIn("api_key", settings)

    def test_model_catalog_uses_hermes_inventory_and_validates_provider(self) -> None:
        payload = {
            "provider": "zai",
            "selected": {"id": "zai", "name": "Z.AI", "authenticated": True},
            "providers": [{"id": "zai", "name": "Z.AI", "authenticated": True}],
            "models": [{"id": "glm-5-turbo", "name": "glm-5-turbo"}],
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        with mock.patch.object(self.api, "docker_exec", return_value=completed) as execute:
            result = self.api.hermes_model_catalog("zai")
        self.assertEqual(result["models"][0]["id"], "glm-5-turbo")
        self.assertIn("zai", execute.call_args.args[0])
        with self.assertRaises(ValueError):
            self.api.hermes_model_catalog("../../bad")

    def test_audit_redacts_secret_fields(self) -> None:
        self.api.audit("test", api_key="secret-value", nested={"token": "token-value"})
        text = self.api.AUDIT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("secret-value", text)
        self.assertNotIn("token-value", text)
        self.assertIn("[redacted]", text)

    def test_hermes_session_id_and_goal_check_markers_are_parsed(self) -> None:
        self.assertEqual(
            self.api.SESSION_RE.findall("response\n\nsession_id: 20260724_025551_4f8883"),
            ["20260724_025551_4f8883"],
        )
        self.assertEqual(
            self.api.SESSION_LINE_RE.sub(
                "",
                "SPARK_OPERATOR_SMOKE_OK\n\nsession_id: 20260724_025551_4f8883",
            ).strip(),
            "SPARK_OPERATOR_SMOKE_OK",
        )
        data = self.root / "hermes-checks"
        (data / "cron").mkdir(parents=True)
        (data / "cron" / "jobs.json").write_text(
            """{"jobs":[{"id":"job-1","name":"Health","prompt":"[spark-operator goal=goal-1]\\nCheck health","enabled":true,"schedule_display":"0 8 * * *"}]}""",
            encoding="utf-8",
        )
        self.api.HERMES_DATA = data
        checks = self.api.read_checks()
        self.assertEqual(checks[0]["goal_id"], "goal-1")
        self.assertEqual(checks[0]["prompt"], "Check health")

    def test_turn_enables_the_sparkbench_mcp_toolset(self) -> None:
        turn_id = "turn-toolset"
        self.api.atomic_json(
            self.api.turn_path(turn_id),
            {"id": turn_id, "state": "queued", "message": "Check health"},
        )
        completed = subprocess.CompletedProcess(
            [],
            0,
            "healthy\nsession_id: session_123456\n",
            "",
        )
        with mock.patch.object(self.api, "docker_exec", return_value=completed) as execute:
            self.api.run_turn(turn_id, "Check health", None)
        args = execute.call_args.args[0]
        self.assertEqual(args[args.index("--toolsets") + 1], "sparkbench")
        self.assertNotIn("sparkbench:get_system_status", args)
        self.assertEqual(self.api.load_json(self.api.turn_path(turn_id), {})["state"], "succeeded")

    def test_provider_update_uses_hermes_assignment_and_recreates_container(self) -> None:
        hermes_root = self.root / "managed-hermes"
        data = hermes_root / "data" / "spark-bot" / "data"
        data.mkdir(parents=True)
        (data / "config.yaml").write_text(
            "model:\n  provider: openrouter\n  default: old-model\n",
            encoding="utf-8",
        )
        (data / ".env").write_text("", encoding="utf-8")
        (hermes_root / "sparkbench-compose.yml").write_text("services: {}\n", encoding="utf-8")
        self.api.HERMES_ROOT = hermes_root
        self.api.HERMES_DATA = data
        token_path = self.root / "install-token"
        token_path.write_text("test-install-token\n", encoding="utf-8")
        self.api.INSTALL_TOKEN_PATH = token_path
        with (
            mock.patch.object(self.api, "docker_exec") as execute,
            mock.patch.object(
                self.api,
                "hermes_model_catalog",
                return_value={
                    "selected": {
                        "id": "openrouter",
                        "authenticated": True,
                        "key_env": "OPENROUTER_API_KEY",
                    }
                },
            ),
            mock.patch.object(
                self.api,
                "run_command",
                return_value=subprocess.CompletedProcess([], 0, "ok", ""),
            ) as run,
        ):
            self.api.update_provider(
                {
                    "confirm": True,
                    "provider": "openrouter",
                    "model": "new-model",
                },
                "test-install-token",
            )
        command = run.call_args.args[0]
        self.assertIn("--force-recreate", command)
        assignment = execute.call_args.args[0]
        self.assertIn("_apply_model_assignment_sync", assignment[2])
        self.assertEqual(assignment[-2:], ["openrouter", "new-model"])

    def test_provider_update_requires_hermes_configuration(self) -> None:
        with (
            mock.patch.object(self.api, "install_token_ok", return_value=True),
            mock.patch.object(
                self.api,
                "hermes_model_catalog",
                return_value={"selected": {"id": "anthropic", "authenticated": False}},
            ),
        ):
            with self.assertRaisesRegex(ValueError, "Hermes dashboard"):
                self.api.update_provider(
                    {"confirm": True, "provider": "anthropic", "model": "claude"},
                    "token",
                )


if __name__ == "__main__":
    unittest.main()
