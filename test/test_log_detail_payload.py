from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from services.config import config
from services.log_service import LoggedCall, append_upstream_http_trace, log_service


class LoggedCallDetailPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._origin_path = log_service.path
        self._origin_log_upstream_http = config.data.get("log_upstream_http")
        self._origin_log_upstream_http_failed_only = config.data.get("log_upstream_http_failed_only")
        config.data["log_upstream_http"] = True
        config.data["log_upstream_http_failed_only"] = False
        log_service.path = Path(self._tmpdir.name) / "logs.jsonl"
        log_service.path.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        log_service.path = self._origin_path
        if self._origin_log_upstream_http is None:
            config.data.pop("log_upstream_http", None)
        else:
            config.data["log_upstream_http"] = self._origin_log_upstream_http
        if self._origin_log_upstream_http_failed_only is None:
            config.data.pop("log_upstream_http_failed_only", None)
        else:
            config.data["log_upstream_http_failed_only"] = self._origin_log_upstream_http_failed_only
        self._tmpdir.cleanup()

    def test_json_call_logs_request_and_response(self) -> None:
        async def run_call() -> None:
            payload = {"model": "auto", "messages": [{"role": "user", "content": "hello"}]}

            def handler(body: dict[str, object]) -> dict[str, object]:
                self.assertEqual(body["model"], "auto")
                return {"id": "resp-1", "ok": True}

            call = LoggedCall(
                {"id": "k1", "name": "demo", "role": "user"},
                "/v1/chat/completions",
                "auto",
                "文本生成",
                request_headers={"x-test": "yes"},
                request_body=payload,
            )
            result = await call.run(handler, payload)
            self.assertEqual(result["id"], "resp-1")

        asyncio.run(run_call())
        items = log_service.list(type="call")
        self.assertEqual(len(items), 1)
        detail = items[0]["detail"]
        self.assertEqual(detail["request"]["headers"]["x-test"], "yes")
        self.assertEqual(detail["request"]["body"]["messages"][0]["content"], "hello")
        self.assertEqual(detail["response"]["status_code"], 200)
        self.assertEqual(detail["response"]["body"]["id"], "resp-1")

    def test_binary_payload_is_serialized(self) -> None:
        call = LoggedCall(
            {"id": "k2", "name": "demo", "role": "user"},
            "/v1/images/edits",
            "gpt-image-2",
            "图生图",
            request_headers={"content-type": "multipart/form-data"},
            request_body={"images": [(b"\x89PNG", "a.png", "image/png")]},
        )
        call.log("调用完成", response_status_code=200, response_headers={"content-type": "application/json"}, response_body={"ok": True})
        items = log_service.list(type="call")
        self.assertEqual(len(items), 1)
        image_meta = items[0]["detail"]["request"]["body"]["images"][0][0]
        self.assertEqual(image_meta["__type__"], "bytes")
        self.assertEqual(image_meta["size"], 4)

    def test_upstream_http_trace_is_attached_and_cleared(self) -> None:
        async def run_first_call() -> None:
            def handler(_: dict[str, object]) -> dict[str, object]:
                append_upstream_http_trace(
                    {
                        "method": "POST",
                        "url": "https://chatgpt.com/backend-api/conversation",
                        "response": {"status_code": 200},
                    }
                )
                return {"ok": True}

            call = LoggedCall(
                {"id": "k3", "name": "demo", "role": "user"},
                "/v1/chat/completions",
                "auto",
                "文本生成",
                request_headers={},
                request_body={"model": "auto"},
            )
            await call.run(handler, {"model": "auto"})

        async def run_second_call() -> None:
            def handler(_: dict[str, object]) -> dict[str, object]:
                return {"ok": True}

            call = LoggedCall(
                {"id": "k4", "name": "demo", "role": "user"},
                "/v1/chat/completions",
                "auto",
                "文本生成",
                request_headers={},
                request_body={"model": "auto"},
            )
            await call.run(handler, {"model": "auto"})

        asyncio.run(run_first_call())
        asyncio.run(run_second_call())
        items = log_service.list(type="call", limit=10)
        self.assertEqual(len(items), 2)
        self.assertTrue(isinstance(items[1]["detail"].get("upstream_http"), list))
        self.assertEqual(items[1]["detail"]["upstream_http"][0]["url"], "https://chatgpt.com/backend-api/conversation")
        self.assertNotIn("upstream_http", items[0]["detail"])

    def test_upstream_http_disabled_by_default_switch(self) -> None:
        config.data["log_upstream_http"] = False

        async def run_call() -> None:
            def handler(_: dict[str, object]) -> dict[str, object]:
                append_upstream_http_trace(
                    {
                        "method": "GET",
                        "url": "https://chatgpt.com/",
                    }
                )
                return {"ok": True}

            call = LoggedCall(
                {"id": "k5", "name": "demo", "role": "user"},
                "/v1/chat/completions",
                "auto",
                "文本生成",
                request_headers={},
                request_body={"model": "auto"},
            )
            await call.run(handler, {"model": "auto"})

        asyncio.run(run_call())
        items = log_service.list(type="call", limit=10)
        self.assertEqual(len(items), 1)
        self.assertNotIn("upstream_http", items[0]["detail"])

    def test_upstream_http_failed_only_filter(self) -> None:
        config.data["log_upstream_http"] = True
        config.data["log_upstream_http_failed_only"] = True

        async def run_call() -> None:
            def handler(_: dict[str, object]) -> dict[str, object]:
                append_upstream_http_trace(
                    {
                        "method": "GET",
                        "url": "https://chatgpt.com/success",
                        "response": {"status_code": 200},
                        "error": "",
                    }
                )
                append_upstream_http_trace(
                    {
                        "method": "POST",
                        "url": "https://chatgpt.com/fail",
                        "response": {"status_code": 502},
                        "error": "",
                    }
                )
                return {"ok": True}

            call = LoggedCall(
                {"id": "k6", "name": "demo", "role": "user"},
                "/v1/chat/completions",
                "auto",
                "文本生成",
                request_headers={},
                request_body={"model": "auto"},
            )
            await call.run(handler, {"model": "auto"})

        asyncio.run(run_call())
        items = log_service.list(type="call", limit=10)
        self.assertEqual(len(items), 1)
        traces = items[0]["detail"].get("upstream_http")
        self.assertTrue(isinstance(traces, list))
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["url"], "https://chatgpt.com/fail")
