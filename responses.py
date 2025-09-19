"""Minimal stub of the ``responses`` library for offline testing."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from unittest import mock

import requests


GET = "GET"
POST = "POST"
PUT = "PUT"
DELETE = "DELETE"


@dataclass
class _RegisteredCall:
    method: str
    url: str
    status: int
    headers: Dict[str, str]
    body: Any


@dataclass
class _CallRecord:
    request: requests.PreparedRequest
    response: requests.Response


class _ResponsesMock:
    def __init__(self) -> None:
        self.calls: List[_CallRecord] = []
        self._registry: List[_RegisteredCall] = []
        self._patcher: Optional[mock._patch] = None

    def __enter__(self) -> "_ResponsesMock":
        self._patcher = mock.patch("requests.sessions.Session.request", side_effect=self._dispatch)
        self._patcher.start()
        self.calls.clear()
        self._registry.clear()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._patcher is not None:
            self._patcher.stop()
            self._patcher = None
        self.calls.clear()
        self._registry.clear()

    def add(self, method: str, url: str, *, status: int = 200, headers: Optional[Dict[str, str]] = None, body: Any = "") -> None:
        self._registry.append(_RegisteredCall(method.upper(), url, status, headers or {}, body))

    def _dispatch(self, method: str, url: str, **kwargs) -> requests.Response:
        if not self._registry:
            raise AssertionError(f"No mocked response available for {method} {url}")
        registered = self._registry.pop(0)
        if registered.method != method.upper() or registered.url != url:
            raise AssertionError(
                f"Unexpected request {method.upper()} {url}; next registered is {registered.method} {registered.url}"
            )

        response = requests.Response()
        response.status_code = registered.status
        response.headers = registered.headers
        if isinstance(registered.body, bytes):
            content = registered.body
        else:
            content = str(registered.body).encode("utf-8")
        response._content = content
        response.url = url
        request = requests.Request(method=method.upper(), url=url).prepare()
        response.request = request
        self.calls.append(_CallRecord(request=request, response=response))
        return response


class _CallsProxy:
    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(_get_active_mock().calls)

    def __iter__(self):  # pragma: no cover - not used but keeps parity
        return iter(_get_active_mock().calls)

    def __getitem__(self, item):  # pragma: no cover - compatibility
        return _get_active_mock().calls[item]


_state = {"mock": None}  # type: ignore[var-annotated]


def _get_active_mock() -> _ResponsesMock:
    mock_obj = _state.get("mock")
    if mock_obj is None:
        raise RuntimeError("responses mock is not active; use @responses.activate")
    return mock_obj


def add(method: str, url: str, **kwargs) -> None:
    _get_active_mock().add(method, url, **kwargs)


def activate(func: Optional[Callable] = None):
    context = _ResponsesContext()
    if func is None:
        return context

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with context:
            return func(*args, **kwargs)

    return wrapper


class _ResponsesContext:
    def __init__(self) -> None:
        self._mock = _ResponsesMock()

    def __enter__(self) -> _ResponsesMock:
        _state["mock"] = self._mock
        return self._mock.__enter__()

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self._mock.__exit__(exc_type, exc, tb)
        finally:
            _state["mock"] = None


calls = _CallsProxy()
