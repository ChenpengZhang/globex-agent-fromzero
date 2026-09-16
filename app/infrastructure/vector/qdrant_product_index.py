import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)

from app.domain.catalog.ports.retrieval_ports import (
    ProductVectorIndex,
    VectorHit,
)
from app.domain.catalog.product import Product
from app.infrastructure.settings import Settings


def _point_id(product_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"globex/product/{product_id}",
        )
    )


class QdrantProductIndex(ProductVectorIndex):
    def __init__(
        self,
        settings: Settings,
    ) -> None:
        if settings.qdrant_url:
            self._client = AsyncQdrantClient(
                url=settings.qdrant_url,
            )
        else:
            local_path = (
                settings.data_dir
                / "qdrant_product_vectors"
            )
            local_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            self._client = AsyncQdrantClient(
                path=str(local_path),
            )

        self._collection = (
            settings.product_vector_collection
        )

    async def ensure_ready(
        self,
        vector_dim: int,
    ) -> None:
        exists = await self._client.collection_exists(
            self._collection,
        )

        if exists:
            return

        await self._client.create_collection(
            collection_name=self._collection,
            vectors_config=VectorParams(
                size=vector_dim,
                distance=Distance.COSINE,
            ),
        )

    async def upsert_products(
        self,
        products: list[Product],
        embeddings: list[list[float]],
        fingerprints: list[str],
    ) -> None:
        if len(products) != len(embeddings) or len(products) != len(fingerprints):
            raise ValueError(
                "products 与 embeddings 数量不一致"
            )

        if not products:
            return

        points = [
            PointStruct(
                id=_point_id(product.product_id),
                vector=embedding,
                payload={
                    "product_id": product.product_id,
                    "fingerprint": fingerprint,
                    # save id and fingerprint in order to update if 
                    # the product description etc changed.
                },
            )
            for product, embedding, fingerprint in zip(
                products,
                embeddings,
                fingerprints,
            )
        ]

        await self._client.upsert(
            collection_name=self._collection,
            points=points,
            wait=True,
        )

    async def get_fingerprints_dict(
        self, 
        product_ids: list[str],
    ) -> dict[str, str]:
        if not product_ids:
            return {}

        exists = await self._client.collection_exists(
            self._collection,
        )
        if not exists:
            return {}

        fingerprints: dict[str, str] = {}

        for start in range(0, len(product_ids), 100):
            # get payload in batches of 100, change this if needed
            batch = product_ids[start : start + 100]

            points = await self._client.retrieve(
                collection_name=self._collection,
                ids=[_point_id(product_id) for product_id in batch],
                with_payload=[
                    "product_id",
                    "fingerprint",
                ],
                with_vectors=False,
            )

            for point in points:
                payload = point.payload or {}
                product_id = payload.get("product_id")
                fingerprint = payload.get("fingerprint")

                if (
                    isinstance(product_id, str)
                    and isinstance(fingerprint, str)
                ):
                    fingerprints[product_id] = fingerprint

        return fingerprints

    async def search(
        self,
        embedding: list[float],
        top_n: int,
    ) -> list[VectorHit]:
        result = await self._client.query_points(
            collection_name=self._collection,
            query=embedding,
            limit=top_n,
            with_payload=True,
        )

        return [
            VectorHit(
                product_id=point.payload["product_id"],
                score=point.score,
            )
            for point in result.points
            if point.payload
            and "product_id" in point.payload
        ]

    async def close(self) -> None:
        await self._client.close()
