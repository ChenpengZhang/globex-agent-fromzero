import logging

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
) -> bool:
    try:
        products = await product_repository.list_all()

        if not products:
            logger.warning(
                "商品库为空，跳过向量索引初始化"
            )
            return False

        embeddings = await embedder.embed_batch(
            [
                product.searchable_text()
                for product in products
            ]
        )

        if not embeddings:
            logger.warning(
                "embedding 返回空结果，跳过商品向量建库"
            )
            return False

        await vector_index.ensure_ready(
            vector_dim=len(embeddings[0]),
        )
        await vector_index.upsert_products(
            products=products,
            embeddings=embeddings,
        )

        logger.info(
            "商品向量索引初始化完成：%d 个商品，维度 %d",
            len(products),
            len(embeddings[0]),
        )

        return True

    except Exception as error:
        logger.warning(
            "商品向量索引初始化失败，"
            "商品检索将降级为关键词召回：%s",
            error,
        )
        return False
    