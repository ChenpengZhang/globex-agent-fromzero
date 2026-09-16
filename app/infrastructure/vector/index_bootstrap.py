import logging
import json
import hashlib

from app.domain.catalog.ports.product_repository import (
    ProductRepository,
)
from app.domain.catalog.ports.retrieval_ports import (
    EmbeddingClient,
    ProductVectorIndex,
)


logger = logging.getLogger(__name__)


async def bootstrap_product_index(
    product_repository: ProductRepository,
    embedder: EmbeddingClient,
    vector_index: ProductVectorIndex,
    embedder_namespace: str, 
) -> bool:
    try:
        products = await product_repository.list_all()

        if not products:
            logger.warning(
                "商品库为空，跳过向量索引初始化"
            )
            return False

        texts = [product.searchable_text() for product in products]

        ids = [product.product_id for product in products]

        current_fingerprints = [
            _generate_fingerprint(text, embedder_namespace) 
            for text in texts
        ]

        stored_fingerprints = await vector_index.get_fingerprints_dict(ids)

        pending = []  # all things that needs to be embedded

        for fingerprint, text, product in zip(
            current_fingerprints,
            texts,
            products,
        ):
            if stored_fingerprints.get(product.product_id) != fingerprint:
                # filter out all products that have already been stored
                pending.append((fingerprint, text, product))

        if not pending:
            logger.info(
                "Product vector index is up to date: %d products",
                len(products),
            )
            return True

        embeddings = await embedder.embed_batch(
            [text for _, text, _ in pending]
        )

        if len(embeddings) != len(pending):
            raise ValueError("Embedding batch size does not match pending size")

        vector_dim = len(embeddings[0])

        if vector_dim == 0 or any(
            len(vector) != vector_dim
            for vector in embeddings
        ):
            raise RuntimeError(
                "Embedding vectors have invalid or inconsistent dimensions"
            )

        await vector_index.ensure_ready(
            vector_dim=vector_dim,
        )

        await vector_index.upsert_products(
            products=[product for _, _, product in pending],
            embeddings=embeddings,
            fingerprints=[fingerprint for fingerprint, _, _ in pending],
        )

        logger.info(
            "Product vector bootstrap completed: %d updated, %d unchanged",
            len(pending),
            len(products) - len(pending),
        )
        return True

    except Exception as error:
        logger.warning(
            "商品向量索引初始化失败，"
            "商品检索将降级为关键词召回：%s",
            error,
        )
        return False

def _generate_fingerprint(
    text: str,
    embedding_namespace: str,
) -> str:
    content = json.dumps(
        {
            "namespace": embedding_namespace,
            "text": text,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()