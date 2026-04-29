from __future__ import annotations

import base64
import json
import itertools
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from services.config import DATA_DIR
from utils.helper import anthropic_sse_stream, sse_json_stream

LOG_TYPE_CALL = "call"
LOG_TYPE_ACCOUNT = "account"
MAX_LOG_STRING_LENGTH = 20_000
MAX_LOG_LIST_ITEMS = 100
MAX_LOG_DICT_ITEMS = 100
MAX_LOG_DEPTH = 8
MAX_STREAM_LOG_CHUNKS = 40
MAX_UPSTREAM_HTTP_TRACES = 200
_UPSTREAM_HTTP_TRACE_CONTEXT: ContextVar[list[dict[str, object]] | None] = ContextVar(
    "upstream_http_trace_context",
    default=None,
)


def _truncate_text(value: str, limit: int = MAX_LOG_STRING_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}... (truncated, total_len={len(value)})"


def _serialize_for_log(value: object, *, depth: int = 0) -> object:
    if depth >= MAX_LOG_DEPTH:
        return f"<max-depth reached ({type(value).__name__})>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_text(value)
    if isinstance(value, bytes):
        preview = base64.b64encode(value[:64]).decode("ascii")
        return {
            "__type__": "bytes",
            "size": len(value),
            "preview_base64": preview,
            "truncated": len(value) > 64,
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_LOG_DICT_ITEMS:
                result["__truncated__"] = f"only first {MAX_LOG_DICT_ITEMS} keys kept"
                break
            result[str(key)] = _serialize_for_log(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        serialized = [_serialize_for_log(item, depth=depth + 1) for item in items[:MAX_LOG_LIST_ITEMS]]
        if len(items) > MAX_LOG_LIST_ITEMS:
            serialized.append(f"... truncated {len(items) - MAX_LOG_LIST_ITEMS} items")
        return serialized
    try:
        return _truncate_text(str(value))
    except Exception:
        return f"<unserializable {type(value).__name__}>"


def start_upstream_http_trace_collection() -> None:
    if not is_upstream_http_trace_enabled():
        _UPSTREAM_HTTP_TRACE_CONTEXT.set(None)
        return
    _UPSTREAM_HTTP_TRACE_CONTEXT.set([])


def clear_upstream_http_trace_collection() -> None:
    _UPSTREAM_HTTP_TRACE_CONTEXT.set(None)


def append_upstream_http_trace(entry: dict[str, object]) -> None:
    if not is_upstream_http_trace_enabled():
        return
    traces = _UPSTREAM_HTTP_TRACE_CONTEXT.get()
    if not isinstance(traces, list):
        return
    if len(traces) >= MAX_UPSTREAM_HTTP_TRACES:
        return
    traces.append(_serialize_for_log(entry))


def current_upstream_http_traces() -> list[object]:
    if not is_upstream_http_trace_enabled():
        return []
    traces = _UPSTREAM_HTTP_TRACE_CONTEXT.get()
    if not isinstance(traces, list):
        return []
    return [_serialize_for_log(item) for item in traces]


def is_upstream_http_trace_enabled() -> bool:
    try:
        from services.config import config
    except Exception:
        return False
    return bool(getattr(config, "log_upstream_http", False))


def is_upstream_http_trace_failed_only() -> bool:
    try:
        from services.config import config
    except Exception:
        return False
    return bool(getattr(config, "log_upstream_http_failed_only", False))


def _is_failed_upstream_trace(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    error = str(item.get("error") or "").strip()
    if error:
        return True
    response = item.get("response")
    status_raw = response.get("status_code") if isinstance(response, dict) else None
    try:
        status_code = int(status_raw)
    except Exception:
        status_code = 0
    return not (200 <= status_code < 400)


class LogService:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, type: str, summary: str = "", detail: dict[str, Any] | None = None, **data: Any) -> None:
        item = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": type,
            "summary": summary,
            "detail": detail or data,
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")

    def list(self, type: str = "", start_date: str = "", end_date: str = "", limit: int = 200) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        items: list[dict[str, Any]] = []
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
            try:
                item = json.loads(line)
            except Exception:
                continue
            t = str(item.get("time") or "")
            day = t[:10]
            if type and item.get("type") != type:
                continue
            if start_date and day < start_date:
                continue
            if end_date and day > end_date:
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return items


log_service = LogService(DATA_DIR / "logs.jsonl")


def _collect_urls(value: object) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "url" and isinstance(item, str):
                urls.append(item)
            elif key == "urls" and isinstance(item, list):
                urls.extend(str(url) for url in item if isinstance(url, str))
            else:
                urls.extend(_collect_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_collect_urls(item))
    return urls


def _image_error_response(exc: Exception) -> JSONResponse:
    message = str(exc)
    if "no available image quota" in message.lower():
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": "no available image quota",
                    "type": "insufficient_quota",
                    "param": None,
                    "code": "insufficient_quota",
                }
            },
        )
    if hasattr(exc, "to_openai_error") and hasattr(exc, "status_code"):
        return JSONResponse(status_code=int(exc.status_code), content=exc.to_openai_error())
    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "message": message,
                "type": "server_error",
                "param": None,
                "code": "upstream_error",
            }
        },
    )


def _json_response_payload(response: JSONResponse) -> object:
    try:
        body = response.body.decode("utf-8")
    except Exception:
        return None
    try:
        return json.loads(body)
    except Exception:
        return body


def _next_item(items):
    try:
        return True, next(items)
    except StopIteration:
        return False, None


@dataclass
class LoggedCall:
    identity: dict[str, object]
    endpoint: str
    model: str
    summary: str
    request_headers: dict[str, object] = field(default_factory=dict)
    request_body: object = None
    started: float = field(default_factory=time.time)

    def _clear_upstream_http_traces(self) -> None:
        clear_upstream_http_trace_collection()

    async def run(self, handler, *args, sse: str = "openai"):
        from services.protocol.conversation import ImageGenerationError

        start_upstream_http_trace_collection()
        try:
            result = await run_in_threadpool(handler, *args)
        except ImageGenerationError as exc:
            response = _image_error_response(exc)
            self.log(
                "调用失败",
                status="failed",
                error=str(exc),
                response_status_code=int(response.status_code),
                response_headers={"content-type": "application/json"},
                response_body=_json_response_payload(response),
            )
            self._clear_upstream_http_traces()
            return response
        except HTTPException as exc:
            self.log(
                "调用失败",
                status="failed",
                error=str(exc.detail),
                response_status_code=int(exc.status_code),
                response_headers={"content-type": "application/json"},
                response_body=exc.detail,
            )
            self._clear_upstream_http_traces()
            raise
        except Exception as exc:
            self.log(
                "调用失败",
                status="failed",
                error=str(exc),
                response_status_code=502,
                response_headers={"content-type": "application/json"},
                response_body={"error": str(exc)},
            )
            self._clear_upstream_http_traces()
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

        if isinstance(result, dict):
            self.log(
                "调用完成",
                result,
                response_status_code=200,
                response_headers={"content-type": "application/json"},
                response_body=result,
            )
            self._clear_upstream_http_traces()
            return result

        sender = anthropic_sse_stream if sse == "anthropic" else sse_json_stream
        try:
            has_first, first = await run_in_threadpool(_next_item, result)
        except ImageGenerationError as exc:
            response = _image_error_response(exc)
            self.log(
                "调用失败",
                status="failed",
                error=str(exc),
                response_status_code=int(response.status_code),
                response_headers={"content-type": "application/json"},
                response_body=_json_response_payload(response),
            )
            self._clear_upstream_http_traces()
            return response
        except HTTPException as exc:
            self.log(
                "调用失败",
                status="failed",
                error=str(exc.detail),
                response_status_code=int(exc.status_code),
                response_headers={"content-type": "application/json"},
                response_body=exc.detail,
            )
            self._clear_upstream_http_traces()
            raise
        except Exception as exc:
            self.log(
                "调用失败",
                status="failed",
                error=str(exc),
                response_status_code=502,
                response_headers={"content-type": "application/json"},
                response_body={"error": str(exc)},
            )
            self._clear_upstream_http_traces()
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        if not has_first:
            self.log(
                "流式调用结束",
                response_status_code=200,
                response_headers={"content-type": "text/event-stream"},
                response_body={"stream": True, "chunk_count": 0, "chunks": []},
            )
            self._clear_upstream_http_traces()
            return StreamingResponse(sender(()), media_type="text/event-stream")
        return StreamingResponse(sender(self.stream(itertools.chain([first], result))), media_type="text/event-stream")

    def stream(self, items):
        urls: list[str] = []
        chunks: list[object] = []
        chunk_count = 0
        chunks_truncated = False
        failed = False
        try:
            for item in items:
                chunk_count += 1
                if len(chunks) < MAX_STREAM_LOG_CHUNKS:
                    chunks.append(_serialize_for_log(item))
                else:
                    chunks_truncated = True
                urls.extend(_collect_urls(item))
                yield item
        except Exception as exc:
            failed = True
            self.log(
                "流式调用失败",
                status="failed",
                error=str(exc),
                urls=urls,
                response_status_code=502,
                response_headers={"content-type": "text/event-stream"},
                response_body={
                    "stream": True,
                    "chunk_count": chunk_count,
                    "chunks": chunks,
                    "chunks_truncated": chunks_truncated,
                },
            )
            self._clear_upstream_http_traces()
            raise
        finally:
            if not failed:
                self.log(
                    "流式调用结束",
                    urls=urls,
                    response_status_code=200,
                    response_headers={"content-type": "text/event-stream"},
                    response_body={
                        "stream": True,
                        "chunk_count": chunk_count,
                        "chunks": chunks,
                        "chunks_truncated": chunks_truncated,
                    },
                )
                self._clear_upstream_http_traces()

    def log(self, suffix: str, result: object = None, status: str = "success", error: str = "",
            urls: list[str] | None = None, response_status_code: int | None = None,
            response_headers: dict[str, object] | None = None, response_body: object = None) -> None:
        detail = {
            "key_id": self.identity.get("id"),
            "key_name": self.identity.get("name"),
            "role": self.identity.get("role"),
            "endpoint": self.endpoint,
            "model": self.model,
            "started_at": datetime.fromtimestamp(self.started).strftime("%Y-%m-%d %H:%M:%S"),
            "ended_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration_ms": int((time.time() - self.started) * 1000),
            "status": status,
        }
        if error:
            detail["error"] = error
        detail["request"] = {
            "headers": _serialize_for_log(self.request_headers),
            "body": _serialize_for_log(self.request_body),
        }
        detail["response"] = {
            "status_code": response_status_code,
            "headers": _serialize_for_log(response_headers or {}),
            "body": _serialize_for_log(response_body),
        }
        upstream_http = current_upstream_http_traces()
        if is_upstream_http_trace_failed_only():
            upstream_http = [item for item in upstream_http if _is_failed_upstream_trace(item)]
        if upstream_http:
            detail["upstream_http"] = upstream_http
        collected_urls = [*(urls or []), *_collect_urls(result)]
        if collected_urls:
            detail["urls"] = list(dict.fromkeys(collected_urls))
        log_service.add(LOG_TYPE_CALL, f"{self.summary}{suffix}", detail)
