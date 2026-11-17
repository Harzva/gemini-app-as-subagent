#!/usr/bin/env python3
"""Offline smoke tests for gemini_subagent.py and gemini_collab_mcp.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_SCRIPT = REPO_ROOT / "scripts" / "gemini_subagent.py"
MCP_SCRIPT = REPO_ROOT / "scripts" / "gemini_collab_mcp.py"


class SubagentSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state_dir = self.root / "state"
        self.collab_dir = self.root / "collab"
        self.sample_file = self.root / "sample.txt"
        self.sample_file.write_text("hello subagent\n", encoding="utf-8")

        self.env = os.environ.copy()
        self.env["GEMINI_SUBAGENT_STATE_DIR"] = str(self.state_dir)
        self.env["GEMINI_COLLAB_DIR"] = str(self.collab_dir)
        self.env["GEMINI_SUBAGENT_CONFIG"] = str(self.root / "nonexistent-config.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI_SCRIPT), *args],
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_help_lists_all_subcommands(self) -> None:
        proc = self.run_cli("--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for cmd in ("doctor", "ask", "review", "research", "sandbox", "status", "agy-ask", "image", "video", "open-app", "handoff", "collect"):
            self.assertIn(cmd, proc.stdout)

    def test_image_help_and_deeplink_flags(self) -> None:
        img_help = self.run_cli("image", "--help")
        self.assertEqual(img_help.returncode, 0, img_help.stderr)
        for flag in ("--style", "knowledge-card", "arch-diagram", "cover-poster", "--tier", "--aspect-ratio", "--size", "--continue-id"):
            self.assertIn(flag, img_help.stdout)

        open_dry = self.run_cli("open-app", "videos", "--dry-run")
        self.assertEqual(open_dry.returncode, 0, open_dry.stderr)
        self.assertEqual(open_dry.stdout.strip(), "googlegemini://?target=videos")

        ho = self.run_cli("handoff", "Image studio check", "--target", "images", "--json")
        self.assertEqual(ho.returncode, 0, ho.stderr)
        ho_data = json.loads(ho.stdout)
        self.assertEqual(ho_data["target"], "images")
        self.assertEqual(ho_data["target_deeplink"], "googlegemini://?target=images")

    def test_handoff_and_collect_roundtrip(self) -> None:
        ho = self.run_cli(
            "handoff",
            "Read sample file and summarize",
            "-f",
            str(self.sample_file),
            "--title",
            "Smoke Test",
            "--json",
        )
        self.assertEqual(ho.returncode, 0, ho.stderr)
        data = json.loads(ho.stdout)
        hid = data["handoff_id"]
        inbox_file = Path(data["inbox_file"])
        outbox_file = Path(data["expected_outbox_file"])
        self.assertTrue(inbox_file.is_file())
        self.assertFalse(outbox_file.exists())

        ls_pending = self.run_cli("collect", "--list", "--json")
        self.assertEqual(ls_pending.returncode, 0, ls_pending.stderr)
        tasks = json.loads(ls_pending.stdout)["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["handoff_id"], hid)
        self.assertEqual(tasks[0]["status"], "PENDING")

        outbox_file.write_text("# Summary\n\nAll good.\n", encoding="utf-8")
        collected = self.run_cli("collect", hid, "--archive", "--json")
        self.assertEqual(collected.returncode, 0, collected.stderr)
        col_data = json.loads(collected.stdout)
        self.assertEqual(col_data["status"], "DONE")
        self.assertTrue(col_data["archived"])
        self.assertIn("All good.", col_data["content"])
        self.assertFalse(inbox_file.exists())
        self.assertTrue((self.collab_dir / "archive" / f"{hid}.md").is_file())

    def test_mcp_stdio_roundtrip(self) -> None:
        ho = self.run_cli("handoff", "MCP roundtrip test", "-f", str(self.sample_file), "--json")
        self.assertEqual(ho.returncode, 0, ho.stderr)
        hid = json.loads(ho.stdout)["handoff_id"]

        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "collab_list_tasks", "arguments": {"status": "pending"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "collab_read_task", "arguments": {"handoff_id": hid}}},
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "collab_submit_result", "arguments": {"handoff_id": hid, "result_markdown": "# MCP Done\n"}},
            },
        ]
        stdin_payload = "\n".join(json.dumps(r) for r in requests) + "\n"
        proc = subprocess.run(
            [sys.executable, str(MCP_SCRIPT)],
            env=self.env,
            input=stdin_payload,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(line) for line in proc.stdout.strip().splitlines() if line.strip()]
        self.assertEqual([r["id"] for r in responses], [1, 2, 3, 4, 5])

        tool_names = [t["name"] for t in responses[1]["result"]["tools"]]
        self.assertEqual(tool_names, ["collab_list_tasks", "collab_read_task", "collab_submit_result"])

        listed = json.loads(responses[2]["result"]["content"][0]["text"])
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["tasks"][0]["handoff_id"], hid)

        read_text = responses[3]["result"]["content"][0]["text"]
        self.assertIn("MCP roundtrip test", read_text)

        submitted = json.loads(responses[4]["result"]["content"][0]["text"])
        self.assertEqual(submitted["status"], "done")
        self.assertTrue(submitted["archived_inbox"])
        self.assertTrue((self.collab_dir / "outbox" / f"{hid}-RESULT.md").is_file())


if __name__ == "__main__":
    unittest.main()
