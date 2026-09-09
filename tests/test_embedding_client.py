import json
from types import SimpleNamespace

import httpx
import pytest

import app.infrastructure.embedding.openai_embedding_client as embedding_module
from app.infrastructure.embedding.openai_embedding_client import (
    OpenAIEmbeddingClient,
)


def build_client() -> OpenAIEmbeddingClient:
    settings = SimpleNamespace(
        embedding_base_url="https://embedding.example/v1/",
        embedding_api_key="test-embedding-key",
        embedding_model="test-embedding-model",
    )

    return OpenAIEmbeddingClient(
        settings,  # type: ignore[arg-type]
        timeout_seconds=3.0,
    )


def install_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler,
) -> None:
    async_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    )

    monkeypatch.setattr(
        embedding_module.httpx,
        "AsyncClient",
        lambda *, timeout: async_client,
    )


@pytest.mark.asyncio
async def test_embed_batch_splits_requests_and_restores_index_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(
            {
                "url": str(request.url),
                "authorization": request.headers[
                    "Authorization"
                ],
                "body": body,
            }
        )

        data = [
            {
                "index": index,
                "embedding": [float(index), float(len(text))],
            }
            for index, text in enumerate(body["input"])
        ]

        return httpx.Response(
            status_code=200,
            json={
                "data": list(reversed(data)),
            },
        )

    install_mock_transport(monkeypatch, handler)
    client = build_client()
    texts = [f"product-{index}" for index in range(11)]

    vectors = await client.embed_batch(texts)

    assert len(requests) == 2
    assert requests[0] == {
        "url": "https://embedding.example/v1/embeddings",
        "authorization": "Bearer test-embedding-key",
        "body": {
            "model": "test-embedding-model",
            "input": texts[:10],
        },
    }
    assert requests[1]["body"]["input"] == texts[10:]
    assert vectors[:10] == [
        [float(index), float(len(text))]
        for index, text in enumerate(texts[:10])
    ]
    assert vectors[10:] == [
        [0.0, float(len(texts[10]))],
    ]


@pytest.mark.asyncio
async def test_embed_delegates_to_single_item_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "data": [
                    {
                        "index": 0,
                        "embedding": [0.25, 0.75],
                    }
                ],
            },
        )

    install_mock_transport(monkeypatch, handler)

    assert await build_client().embed("travel bag") == [
        0.25,
        0.75,
    ]


@pytest.mark.asyncio
async def test_embed_batch_returns_empty_without_http_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_client(**kwargs):
        raise AssertionError("空输入不应创建 HTTP client")

    monkeypatch.setattr(
        embedding_module.httpx,
        "AsyncClient",
        unexpected_client,
    )

    assert await build_client().embed_batch([]) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_kwargs", "expected_message"),
    [
        (
            {
                "status_code": 200,
                "content": b"",
            },
            "embedding 服务返回了空响应",
        ),
        (
            {
                "status_code": 200,
                "json": {"unexpected": []},
            },
            "embedding 响应格式错误",
        ),
        (
            {
                "status_code": 200,
                "json": {
                    "data": [
                        {
                            "index": 0,
                            "embedding": [1.0],
                        }
                    ]
                },
            },
            "embedding 返回的向量数量与输入数量不一致",
        ),
    ],
)
async def test_embed_batch_rejects_invalid_responses(
    monkeypatch: pytest.MonkeyPatch,
    response_kwargs: dict,
    expected_message: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(**response_kwargs)

    install_mock_transport(monkeypatch, handler)

    with pytest.raises(
        RuntimeError,
        match=expected_message,
    ):
        await build_client().embed_batch(["one", "two"])
