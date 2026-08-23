import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

import server


class ServerApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(server, "DATA_DIR", Path(self.temporary_directory.name)),
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
        self.temporary_directory.cleanup()

    def request_json(self, path, method="GET", payload=None):
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
