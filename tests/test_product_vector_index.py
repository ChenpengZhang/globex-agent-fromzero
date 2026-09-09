from types import SimpleNamespace

import pytest

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
        )
        await index.upsert_products(
            products=[product],
            embeddings=[[0.0, 1.0]],
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
            )
    finally:
        await index.close()
