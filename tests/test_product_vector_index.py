from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from qdrant_client.models import PointStruct

from app.infrastructure.persistence.seed_products import (
    build_seed_products,
)
from app.infrastructure.vector.qdrant_product_index import (
    QdrantProductIndex,
    _point_id,
)


def build_index(tmp_path) -> QdrantProductIndex:
    settings = SimpleNamespace(
        qdrant_url="",
        data_dir=tmp_path,
        product_vector_collection="test_product_vectors",
    )

    return QdrantProductIndex(
        settings,  # type: ignore[arg-type]
    )


def test_product_point_id_is_stable_and_product_specific() -> None:
    assert _point_id("P1001") == _point_id("P1001")
    assert _point_id("P1001") != _point_id("P1002")


@pytest.mark.asyncio
async def test_fingerprint_lookup_handles_missing_collection_and_legacy_points(tmp_path):
    index = build_index(tmp_path)
    try:
        assert await index.get_fingerprints_dict([]) == {}
        assert await index.get_fingerprints_dict(["legacy"]) == {}
        await index.ensure_ready(vector_dim=2)
        await index._client.upsert(
            collection_name=index._collection,
            points=[PointStruct(
                id=_point_id("legacy"), vector=[1.0, 0.0],
                payload={"product_id": "legacy"},
            )],
            wait=True,
        )
        assert await index.get_fingerprints_dict(["legacy", "missing"]) == {}
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_fingerprint_lookup_batches_ids_without_loading_vectors(tmp_path):
    index = build_index(tmp_path)
    ids = [f"product-{number}" for number in range(205)]
    try:
        await index.ensure_ready(vector_dim=2)
        await index._client.upsert(
            collection_name=index._collection,
            points=[PointStruct(
                id=_point_id(product_id), vector=[1.0, 0.0],
                payload={"product_id": product_id, "fingerprint": product_id},
            ) for product_id in ids],
            wait=True,
        )
        index._client.retrieve = AsyncMock(wraps=index._client.retrieve)
        assert await index.get_fingerprints_dict(ids) == {key: key for key in ids}
        calls = index._client.retrieve.call_args_list
        assert [len(call.kwargs["ids"]) for call in calls] == [100, 100, 5]
        assert all(call.kwargs["with_vectors"] is False for call in calls)
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_product_index_rejects_misaligned_fingerprints(tmp_path):
    index = build_index(tmp_path)
    try:
        with pytest.raises(ValueError):
            await index.upsert_products(
                products=build_seed_products()[:2],
                embeddings=[[1.0, 0.0], [0.0, 1.0]],
                fingerprints=["only-one"],
            )
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_product_index_upserts_and_searches_by_cosine(
    tmp_path,
) -> None:
    index = build_index(tmp_path)
    products = build_seed_products()[:3]

    try:
        await index.ensure_ready(vector_dim=3)
        await index.ensure_ready(vector_dim=3)
        await index.upsert_products(
            products=products,
            fingerprints=["a", "b", "c"],
            embeddings=[
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
        )

        hits = await index.search(
            embedding=[0.9, 0.1, 0.0],
            top_n=2,
        )

        assert len(hits) == 2
        assert hits[0].product_id == products[0].product_id
        assert hits[0].score > hits[1].score
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_product_index_upsert_replaces_same_product_point(
    tmp_path,
) -> None:
    index = build_index(tmp_path)
    product = build_seed_products()[0]

    try:
        await index.ensure_ready(vector_dim=2)
        await index.upsert_products(
            products=[product],
            embeddings=[[1.0, 0.0]],
            fingerprints=["old"],
        )
        await index.upsert_products(
            products=[product],
            embeddings=[[0.0, 1.0]],
            fingerprints=["new"],
        )

        count = await index._client.count(
            collection_name=index._collection,
            exact=True,
        )
        hits = await index.search(
            embedding=[0.0, 1.0],
            top_n=10,
        )

        assert count.count == 1
        assert await index.get_fingerprints_dict([product.product_id]) == {
            product.product_id: "new",
        }
        assert [hit.product_id for hit in hits] == [
            product.product_id,
        ]
        assert hits[0].score == pytest.approx(1.0)
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_product_index_rejects_misaligned_embeddings(
    tmp_path,
) -> None:
    index = build_index(tmp_path)
    products = build_seed_products()[:2]

    try:
        with pytest.raises(
            ValueError,
            match="products 与 embeddings 数量不一致",
        ):
            await index.upsert_products(
                products=products,
                embeddings=[[1.0, 0.0]],
                fingerprints=["a", "b"],
            )
    finally:
        await index.close()
