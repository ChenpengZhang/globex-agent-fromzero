import logging
from pathlib import Path

from agentscope.credential import OpenAICredential
from agentscope.embedding import OpenAIEmbeddingModel
from agentscope.rag import (
    ApproxTokenChunker,
    KnowledgeBase,
    QdrantStore,
    TextParser,
)

from app.infrastructure.settings import (
    PROJECT_ROOT,
    Settings,
)


logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"

_KB_DESCRIPTION = (
    "Globex 跨境电商品类洞察知识库："
    "包含品类定位、热卖款型、关键属性、"
    "价格区间和避坑建议。"
)


def build_category_knowledge_base(
    settings: Settings,
) -> KnowledgeBase:
    """Construct the category KnowledgeBase without ingesting documents."""
    credential = OpenAICredential(
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
    )

    embedding_model = OpenAIEmbeddingModel(
        credential=credential,
        model=settings.embedding_model,
        dimensions=settings.embedding_dim,
        pass_dimensions=False,
    )

    if settings.qdrant_url:
        vector_store = QdrantStore(
            url=settings.qdrant_url,
        )
    else:
        local_path = (
            settings.data_dir
            / "qdrant_category_knowledge"
        )
        local_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        vector_store = QdrantStore(
            path=str(local_path),
        )

    return KnowledgeBase(
        name="category_insight",
        description=_KB_DESCRIPTION,
        embedding_model=embedding_model,
        vector_store=vector_store,
        collection=settings.category_kb_collection,
    )


async def bootstrap_category_knowledge(
    knowledge_base: KnowledgeBase,
    knowledge_dir: Path | None = None,
) -> int:
    """Idempotently ingest Markdown knowledge documents."""
    directory = knowledge_dir or KNOWLEDGE_DIR

    try:
        await knowledge_base.ensure_collection()

        existing_document_ids = {
            document.document_id
            for document
            in await knowledge_base.list_documents()
        }

        parser = TextParser()
        chunker = ApproxTokenChunker(
            chunk_size=512,
            overlap=50,
        )

        inserted = 0

        for markdown_file in sorted(
            directory.glob("*.md")
        ):
            document_id = markdown_file.stem

            if document_id in existing_document_ids:
                continue

            sections = await parser.parse(
                str(markdown_file),
                filename=markdown_file.name,
            )

            chunks = await chunker.chunk(sections)

            await knowledge_base.insert_document(
                chunks=chunks,
                document_id=document_id,
                document_metadata={
                    "source": markdown_file.name,
                },
            )

            inserted += 1

        logger.info(
            "品类知识库初始化完成：新增 %d 篇，"
            "已有 %d 篇",
            inserted,
            len(existing_document_ids),
        )

        return inserted

    except Exception as error:
        logger.warning(
            "品类知识库初始化失败，"
            "category insight 暂时不可用：%s",
            error,
        )
        return 0