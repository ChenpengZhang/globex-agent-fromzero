import json
from types import SimpleNamespace

import httpx
import pytest

import app.infrastructure.rerank.http_reranker as reranker_module
from app.infrastructure.rerank.http_reranker import HttpReranker


def build_reranker() -> HttpReranker:
    settings = SimpleNamespace(
        reranker_base_url="https://reranker.example/v1/",
        reranker_model="test-reranker-model",
    )

    return HttpReranker(
        settings,  # type: ignore[arg-type]
        timeout_seconds=1.5,
    )


def install_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler,
) -> None:
    async_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    )

    monkeypatch.setattr(
        reranker_module.httpx,
        "AsyncClient",
        lambda *, timeout: async_client,
    )


@pytest.mark.asyncio
async def test_reranker_sends_request_and_restores_document_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)

        return httpx.Response(
            status_code=200,
            json={
                "results": [
                    {
                        "index": 2,
                        "relevance_score": 0.95,
                    },
                    {
                        "index": 0,
                        "relevance_score": 0.72,
                    },
                    {
                        "index": 1,
                        "score": 0.31,
                    },
                ]
            },
        )

    install_mock_transport(monkeypatch, handler)
    documents = ["doc zero", "doc one", "doc two"]

    scores = await build_reranker().rerank(
        query="light travel bag",
        documents=documents,
    )

    assert captured == {
        "url": "https://reranker.example/v1/rerank",
        "body": {
            "model": "test-reranker-model",
            "query": "light travel bag",
            "documents": documents,
        },
    }
    assert scores == [0.72, 0.31, 0.95]


@pytest.mark.asyncio
async def test_reranker_skips_http_for_empty_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_client(**kwargs):
        raise AssertionError("空 documents 不应创建 HTTP client")

    monkeypatch.setattr(
        reranker_module.httpx,
        "AsyncClient",
        unexpected_client,
    )

    assert await build_reranker().rerank("query", []) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "expected_message"),
    [
        (
            {"unexpected": []},
            "rerank 响应格式错误",
        ),
        (
            {
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                ]
            },
            "rerank 响应格式错误",
        ),
        (
            {
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.8},
                ]
            },
            "rerank 响应 index 错误",
        ),
        (
            {
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 2, "relevance_score": 0.8},
                ]
            },
            "rerank 响应 index 错误",
        ),
        (
            {
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 1},
                ]
            },
            "rerank 响应 score 错误",
        ),
    ],
)
async def test_reranker_rejects_invalid_protocol_responses(
    monkeypatch: pytest.MonkeyPatch,
    body: dict,
    expected_message: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json=body)

    install_mock_transport(monkeypatch, handler)

    with pytest.raises(RuntimeError, match=expected_message):
        await build_reranker().rerank(
            query="query",
            documents=["one", "two"],
        )


@pytest.mark.asyncio
async def test_reranker_propagates_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=503,
            json={"detail": "temporarily unavailable"},
        )

    install_mock_transport(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError):
        await build_reranker().rerank(
            query="query",
            documents=["one"],
        )
