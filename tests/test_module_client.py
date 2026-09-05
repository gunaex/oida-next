import asyncio

import httpx
import pytest

from oida_next.module_client import ModuleConfig, ModuleUnavailable, ProjectReader


def read(handler, token="module-only-credential"):
    return asyncio.run(
        ProjectReader(
            ModuleConfig("qa", "https://qa.example.test"), httpx.MockTransport(handler)
        ).list_projects(token)
    )


def test_project_contract_and_credential_boundary():
    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == "https://qa.example.test/api/projects"
        assert request.headers["authorization"] == "Bearer module-only-credential"
        assert "cookie" not in request.headers
        return httpx.Response(
            200, json=[{"slug": "alpha", "name": "Alpha", "secret": "not-exported"}]
        )

    assert read(handler) == [{"system": "qa", "external_id": "alpha", "name": "Alpha"}]


@pytest.mark.parametrize("status", [301, 302, 401, 403, 500])
def test_remote_failure_does_not_leak_or_follow(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, headers={"Location": "https://other.test"}, text="sensitive-upstream-message"
        )

    with pytest.raises(ModuleUnavailable) as error:
        read(handler)
    assert "sensitive" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("data", [{}, [None], [{"slug": "x"}], [{"slug": "", "name": "x"}]])
def test_rejects_invalid_contract(data):
    with pytest.raises(ModuleUnavailable):
        read(lambda r: httpx.Response(200, json=data))


def test_size_limit_and_missing_identity():
    with pytest.raises(ModuleUnavailable, match="safe limit"):
        read(lambda r: httpx.Response(200, content=b" " * 1_000_001))
    with pytest.raises(ModuleUnavailable, match="not configured"):
        read(lambda r: pytest.fail("Must not send request"), token="")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test",
        "https://user:password@example.test",
        "https://example.test/api",
        "https://example.test?x=1",
    ],
)
def test_rejects_unsafe_origin(url):
    with pytest.raises(ValueError):
        ModuleConfig("pm", url)
