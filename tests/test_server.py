import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen

import server
from debate_agent import SummaryResult, ViewpointResult


class ServerApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.api_key_names = (
            "MOONSHOT_API_KEY",
            "KIMI_API_KEY",
            "DEEPSEEK_API_KEY",
        )
        self.original_api_keys = {
            key: os.environ.get(key) for key in self.api_key_names
        }
        for key in self.api_key_names:
            os.environ.pop(key, None)
        temporary_path = Path(self.temporary_directory.name)
        self.patches = [
            patch.object(server, "DATA_DIR", temporary_path / "debates"),
            patch.object(server, "ENV_PATH", temporary_path / ".env"),
            patch.object(server, "provider_is_ready", return_value=True),
            patch.object(
                server,
                "default_model",
                side_effect=lambda provider: f"{provider}-test-model",
            ),
            patch.object(server, "start_debate_job"),
        ]
        for active_patch in self.patches:
            active_patch.start()

        self.http_server = ThreadingHTTPServer(
            ("127.0.0.1", 0), server.DebateRequestHandler
        )
        self.base_url = f"http://127.0.0.1:{self.http_server.server_port}"
        self.thread = threading.Thread(
            target=self.http_server.serve_forever,
            daemon=True,
        )
        self.thread.start()

    def tearDown(self):
        self.http_server.shutdown()
        self.http_server.server_close()
        self.thread.join(timeout=2)
        for active_patch in reversed(self.patches):
            active_patch.stop()
        for key in self.api_key_names:
            original_value = self.original_api_keys[key]
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value
        self.temporary_directory.cleanup()

    def request_json(self, path, method="GET", payload=None):
        if path == "/api/debates" and method == "POST" and isinstance(payload, dict):
            payload = dict(payload)
            payload.setdefault("viewpointAgent", {"provider": "kimi"})
            payload.setdefault(
                "viewpoints",
                {"affirmative": "正方确认观点", "negative": "反方确认观点"},
            )
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method=method,
        )
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_create_read_and_stop_debate(self):
        status, payload = self.request_json(
            "/api/debates",
            method="POST",
            payload={
                "topic": "测试辩题",
                "affirmative": {"provider": "kimi"},
                "negative": {"provider": "deepseek"},
            },
        )
        self.assertEqual(status, 201)
        debate = payload["debate"]
        self.assertEqual(debate["affirmative"]["model"], "kimi-test-model")
        self.assertEqual(debate["negative"]["model"], "deepseek-test-model")
        self.assertEqual(debate["summarizer"], debate["negative"])
        self.assertEqual(debate["schemaVersion"], 3)
        self.assertEqual(debate["phase"], "opening")
        self.assertEqual(debate["viewpoints"]["affirmative"], "正方确认观点")
        self.assertEqual(debate["viewpointAgent"]["provider"], "kimi")
        self.assertEqual(
            debate["argumentGraph"],
            {
                "nodes": [],
                "edges": [],
                "updatedThroughRound": 0,
                "resources": {
                    "supportEvidence": {"used": 0, "limit": 4, "remaining": 4},
                    "rebuttalEvidence": {"used": 0, "limit": 10, "remaining": 10},
                },
            },
        )
        self.assertIsNone(debate["currentSpeaker"])
        record_file = server.DATA_DIR / debate["storageFile"]
        self.assertTrue(record_file.exists())
        self.assertEqual(record_file.name, "debate.json")
        self.assertIn("测试辩题", record_file.parent.name)

        status, payload = self.request_json(f"/api/debates/{debate['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["debate"]["topic"], "测试辩题")

        status, payload = self.request_json(
            f"/api/debates/{debate['id']}",
            method="PATCH",
            payload={"status": "stopped"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["debate"]["status"], "stopped")

    def test_selected_kimi_k3_and_deepseek_flash_models_are_preserved(self):
        status, payload = self.request_json(
            "/api/debates",
            method="POST",
            payload={
                "topic": "新模型测试",
                "affirmative": {"provider": "kimi", "model": "kimi-k3"},
                "negative": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                },
                "summarizer": {
                    "provider": "kimi",
                    "model": "kimi-k2.6",
                },
            },
        )

        self.assertEqual(status, 201)
        debate = payload["debate"]
        self.assertEqual(debate["affirmative"]["model"], "kimi-k3")
        self.assertEqual(debate["negative"]["model"], "deepseek-v4-flash")
        self.assertEqual(
            debate["summarizer"],
            {"provider": "kimi", "model": "kimi-k2.6"},
        )

    def test_viewpoint_agent_generates_reviewable_positions(self):
        fake_agent = Mock()
        fake_agent.generate.return_value = ViewpointResult(
            affirmative="人工智能利大于弊",
            negative="人工智能弊大于利",
        )
        with patch.object(server, "ViewpointAgent", return_value=fake_agent) as agent_class:
            status, payload = self.request_json(
                "/api/viewpoints",
                method="POST",
                payload={
                    "topic": "聊聊人工智能的影响",
                    "agent": {"provider": "deepseek", "model": "deepseek-v4-flash"},
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["viewpoints"]["affirmative"], "人工智能利大于弊")
        self.assertEqual(payload["viewpoints"]["negative"], "人工智能弊大于利")
        agent_class.assert_called_once_with(
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        fake_agent.generate.assert_called_once_with(
            topic="聊聊人工智能的影响",
            max_tokens=400,
        )

    def test_graph_update_persists_nodes_edges_and_summary_metadata(self):
        _, payload = self.request_json(
            "/api/debates",
            method="POST",
            payload={
                "topic": "图谱持久化测试",
                "affirmative": {"provider": "kimi"},
                "negative": {"provider": "deepseek"},
                "summarizer": {
                    "provider": "kimi",
                    "model": "kimi-k3",
                },
            },
        )
        debate = payload["debate"]
        record_id = debate["id"]
        with server.WRITE_LOCK:
            record = server.read_record(record_id)
            record["speeches"] = [
                {
                    "id": "speech_a",
                    "round": 1,
                    "side": "affirmative",
                    "content": "正方主张",
                },
                {
                    "id": "speech_n",
                    "round": 1,
                    "side": "negative",
                    "content": "反方反驳",
                },
            ]
            server.write_record(record)

        server.save_graph_update(
            record_id,
            1,
            SummaryResult(
                nodes=[
                    {
                        "key": "a1",
                        "side": "affirmative",
                        "kind": "core_argument",
                        "text": "正方主张",
                        "sourceSpeechId": "speech_a",
                        "sourceQuote": "正方主张",
                    },
                    {
                        "key": "n1",
                        "side": "negative",
                        "kind": "core_argument",
                        "text": "反方反驳",
                        "sourceSpeechId": "speech_n",
                        "sourceQuote": "反方反驳",
                    },
                    {
                        "key": "a_support",
                        "side": "affirmative",
                        "kind": "support_evidence",
                        "text": "正方支持材料",
                        "sourceSpeechId": "speech_a",
                        "sourceQuote": "正方主张",
                    },
                    {
                        "key": "n_rebuttal",
                        "side": "negative",
                        "kind": "rebuttal_evidence",
                        "text": "反方反驳材料",
                        "sourceSpeechId": "speech_n",
                        "sourceQuote": "反方反驳",
                    },
                ],
                edges=[
                    {"from": "n1", "to": "a1", "type": "rebuts"},
                    {"from": "a_support", "to": "a1", "type": "supports"},
                    {"from": "n_rebuttal", "to": "a1", "type": "rebuts"},
                ],
                status="completed",
            ),
        )

        stored = server.read_record(record_id)
        graph = stored["argumentGraph"]
        self.assertEqual(graph["updatedThroughRound"], 1)
        self.assertEqual(len(graph["nodes"]), 4)
        self.assertEqual(len(graph["edges"]), 3)
        self.assertEqual(graph["edges"][0]["type"], "rebuts")
        self.assertIn(
            graph["edges"][0]["from"],
            {node["id"] for node in graph["nodes"]},
        )
        self.assertEqual(stored["roundSummaries"][0]["model"], "kimi-k3")
        self.assertEqual(
            graph["resources"],
            {
                "supportEvidence": {"used": 1, "limit": 4, "remaining": 3},
                "rebuttalEvidence": {"used": 1, "limit": 10, "remaining": 9},
            },
        )
        self.assertEqual(
            stored["roundSummaries"][0]["resources"],
            graph["resources"],
        )

    def test_model_must_belong_to_selected_provider(self):
        self.assertFalse(
            server.DebateRequestHandler.valid_side(
                {"provider": "kimi", "model": "deepseek-v4-flash"}
            )
        )

    def test_api_keys_can_be_saved_without_returning_them(self):
        kimi_key = "unit-test-kimi-key"
        deepseek_key = "unit-test-deepseek-key"

        status, payload = self.request_json(
            "/api/config/keys",
            method="POST",
            payload={
                "keys": {
                    "kimi": kimi_key,
                    "deepseek": deepseek_key,
                }
            },
        )

        self.assertEqual(status, 200)
        self.assertNotIn(kimi_key, json.dumps(payload))
        self.assertNotIn(deepseek_key, json.dumps(payload))
        self.assertEqual(os.environ["MOONSHOT_API_KEY"], kimi_key)
        self.assertEqual(os.environ["DEEPSEEK_API_KEY"], deepseek_key)
        env_contents = server.ENV_PATH.read_text(encoding="utf-8")
        self.assertIn(f"MOONSHOT_API_KEY={kimi_key}", env_contents)
        self.assertIn(f"DEEPSEEK_API_KEY={deepseek_key}", env_contents)

    def test_local_server_refuses_to_share_its_port(self):
        first_server = server.LocalThreadingHTTPServer(
            ("127.0.0.1", 0),
            server.DebateRequestHandler,
        )
        try:
            address = first_server.server_address
            with self.assertRaises(OSError):
                second_server = server.LocalThreadingHTTPServer(
                    address,
                    server.DebateRequestHandler,
                )
                second_server.server_close()
        finally:
            first_server.server_close()

    def test_record_write_retries_transient_windows_permission_error(self):
        record = {
            "id": "debate_20260823T010000Z_deadbeef",
            "topic": "测试写入",
            "status": "running",
            "speeches": [],
        }
        real_replace = server.os.replace
        attempts = 0

        def flaky_replace(source, destination):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise PermissionError(5, "文件正在被短暂占用")
            return real_replace(source, destination)

        with patch.object(server.os, "replace", side_effect=flaky_replace), patch.object(
            server.time, "sleep"
        ):
            server.write_record(record)

        self.assertEqual(attempts, 2)
        self.assertEqual(server.read_record(record["id"])["topic"], "测试写入")
        self.assertEqual(list(server.DATA_DIR.glob("*.tmp")), [])

    def test_pause_request_then_resume_active_job(self):
        _, payload = self.request_json(
            "/api/debates",
            method="POST",
            payload={
                "topic": "测试暂停",
                "affirmative": {"provider": "kimi"},
                "negative": {"provider": "deepseek"},
            },
        )
        record_id = payload["debate"]["id"]
        stop_event = threading.Event()
        pause_event = threading.Event()
        with server.JOB_LOCK:
            server.ACTIVE_JOBS[record_id] = (
                threading.Thread(),
                stop_event,
                pause_event,
            )

        try:
            status, payload = self.request_json(
                f"/api/debates/{record_id}",
                method="PATCH",
                payload={"status": "paused"},
            )
            self.assertEqual(status, 200)
            self.assertTrue(payload["debate"]["pauseRequested"])
            self.assertTrue(pause_event.is_set())

            server.mark_debate_paused(record_id)
            self.assertEqual(server.read_record(record_id)["status"], "paused")

            status, payload = self.request_json(
                f"/api/debates/{record_id}",
                method="PATCH",
                payload={"status": "running"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["debate"]["status"], "running")
            self.assertFalse(pause_event.is_set())
        finally:
            with server.JOB_LOCK:
                server.ACTIVE_JOBS.pop(record_id, None)

    def test_each_debate_creates_a_new_topic_folder(self):
        request_payload = {
            "topic": "相同辩题：利大于弊？",
            "affirmative": {"provider": "deepseek"},
            "negative": {"provider": "deepseek"},
        }

        _, first_payload = self.request_json(
            "/api/debates", method="POST", payload=request_payload
        )
        _, second_payload = self.request_json(
            "/api/debates", method="POST", payload=request_payload
        )

        first = first_payload["debate"]
        second = second_payload["debate"]
        self.assertNotEqual(first["storageFolder"], second["storageFolder"])
        self.assertTrue((server.DATA_DIR / first["storageFile"]).exists())
        self.assertTrue((server.DATA_DIR / second["storageFile"]).exists())
        self.assertTrue(first["storageFolder"].startswith("相同辩题：利大于弊？__debate_"))


if __name__ == "__main__":
    unittest.main()
