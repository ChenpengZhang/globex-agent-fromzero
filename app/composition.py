from dataclasses import dataclass

from agentscope.tool import FunctionTool
from agentscope.rag import KnowledgeBase
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
)

from app.application.memory.preference_selector import (
    PreferenceSelector,
)
from app.application.tools.preference_tools import (
    build_forget_preference_tool,
    build_remember_preference_tool,
)
from app.domain.buyer.ports.preference_store import (
    PreferenceStore,
)
from app.infrastructure.persistence.sql.sql_preference_store import (
    SqlPreferenceStore,
)
from app.infrastructure.persistence.sql.database import (
    bootstrap_schema,
    create_database_engine,
)
from app.infrastructure.persistence.sql.sql_conversation_store import (
    SqlConversationStore,
)
from app.infrastructure.persistence.sql.sql_session_store import (
    SqlSessionStore,
)
from app.domain.catalog.ports.retrieval_ports import (
    EmbeddingClient,
)
from app.domain.session.ports.conversation_store import (
    ConversationStore,
)
from app.infrastructure.embedding.openai_embedding_client import (
    OpenAIEmbeddingClient,
)
from app.infrastructure.vector.index_bootstrap import (
    bootstrap_product_index,
)
from app.infrastructure.vector.qdrant_product_index import (
    QdrantProductIndex,
)
from app.infrastructure.rag.category_knowledge import (
    bootstrap_category_knowledge,
    build_category_knowledge_base,
)
from app.infrastructure.rerank.http_reranker import (
    HttpReranker,
)
from app.infrastructure.eventbus import (
    InMemoryTradeEventBus,
)
from app.application.agents.main_agent import MainAgentFactory
from app.application.agents.orchestrator import (
    MainAgentOrchestrator,
)
from app.application.agents.search_agent import (
    SearchAgentFactory,
)
from app.application.agents.trade_agent import (
    TradeAgentFactory,
)
from app.application.tools.task_dispatch_tool import (
    build_task_dispatch_tool,
)
from app.application.usecases.catalog_search import (
    CatalogSearchUseCase,
)
from app.application.usecases.cancel_order import (
    CancelOrderUseCase,
)
from app.application.usecases.place_order import (
    PlaceOrderUseCase,
)
from app.application.usecases.query_order import (
    QueryOrderUseCase,
)
from app.application.agents.session_registry import (
    SessionRegistry,
)
from app.application.usecases.get_conversation_history import (
    GetConversationHistoryUseCase,
)
from app.domain.catalog.ports.product_repository import (
    ProductRepository,
)
from app.domain.order.ports.order_repository import (
    OrderRepository,
)
from app.infrastructure.llm import create_chat_model
from app.infrastructure.persistence.in_memory_product_repository import (
    InMemoryProductRepository,
)
from app.infrastructure.persistence.seed_products import (
    build_seed_products,
)
from app.infrastructure.persistence.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from app.infrastructure.settings import load_settings


@dataclass
class Container:
    main_agent_factory: MainAgentFactory
    search_agent_factory: SearchAgentFactory
    trade_agent_factory: TradeAgentFactory
    sessions: SessionRegistry
    orchestrator: MainAgentOrchestrator

    product_repository: ProductRepository
    order_repository: OrderRepository
    knowledge_base: KnowledgeBase

    event_bus: InMemoryTradeEventBus
    conversation_store: ConversationStore
    preference_store: PreferenceStore
    get_conversation_history: GetConversationHistoryUseCase
    database_engine: AsyncEngine

    catalog_search: CatalogSearchUseCase
    place_order: PlaceOrderUseCase
    query_order: QueryOrderUseCase
    cancel_order: CancelOrderUseCase

    embedder: EmbeddingClient
    vector_index: QdrantProductIndex
    # The container is the only place where it knows every module

    async def startup(self) -> None:
        """Initialize external resources and searchable data."""
        await bootstrap_schema(
            self.database_engine,
        )

        await self.knowledge_base.vector_store.__aenter__()

        await bootstrap_product_index(
            product_repository=self.product_repository,
            embedder=self.embedder,
            vector_index=self.vector_index,
        )

        await bootstrap_category_knowledge(
            self.knowledge_base,
        )

    async def shutdown(self) -> None:
        """Release external resources."""

        try:
            await self.vector_index.close()
        finally:
            try:
                await self.knowledge_base.vector_store.__aexit__(
                    None,
                    None,
                    None,
                )
            finally:
                await self.database_engine.dispose()

def build_container() -> Container:
    settings = load_settings()

    database_engine = create_database_engine(
        settings.database_url,
    )

    session_factory = async_sessionmaker(
        database_engine,
        expire_on_commit=False,
    )

    embedder = OpenAIEmbeddingClient(settings)

    vector_index = QdrantProductIndex(settings)

    reranker = (
        HttpReranker(settings)
        if settings.reranker_base_url
        else None
    )

    knowledge_base = build_category_knowledge_base(
        settings,
    )

    product_repository = InMemoryProductRepository(
        build_seed_products(),
    )

    catalog_search = CatalogSearchUseCase(
        product_repository,
        embedder=embedder,
        vector_index=vector_index,
        reranker=reranker,
    )

    order_repository = InMemoryOrderRepository()

    place_order = PlaceOrderUseCase(
        product_repository=product_repository,
        order_repository=order_repository,
    )

    query_order = QueryOrderUseCase(
        order_repository=order_repository,
    )

    cancel_order = CancelOrderUseCase(
        product_repository=product_repository,
        order_repository=order_repository,
    )

    model = create_chat_model(settings)

    search_agent_factory = SearchAgentFactory(
        model=model,
        catalog_search=catalog_search,
        knowledge_base=knowledge_base,
    )

    trade_agent_factory = TradeAgentFactory(
        model=model,
        place_order=place_order,
        query_order=query_order,
        cancel_order=cancel_order,
    )

    event_bus = InMemoryTradeEventBus()

    preference_store = SqlPreferenceStore(
        session_factory,
    )

    preference_selector = PreferenceSelector(
        embedder=embedder,
        relevance_enabled=(
            settings.preference_relevance_enabled
        ),
    )

    remember_preference_function = (
        build_remember_preference_tool(
            store=preference_store,
            event_publisher=event_bus,
        )
    )
    remember_preference_tool = FunctionTool(
        remember_preference_function,
        is_read_only=False,
    )

    forget_preference_function = (
        build_forget_preference_tool(
            store=preference_store,
            event_publisher=event_bus,
        )
    )
    forget_preference_tool = FunctionTool(
        forget_preference_function,
        is_read_only=False,
    )

    task_dispatch_function = build_task_dispatch_tool(
        search_factory=search_agent_factory,
        trade_factory=trade_agent_factory,
        preference_store=preference_store,
        preference_selector=preference_selector,
        preference_top_k=settings.preference_top_k,
        inject_preferences=(
            settings.preference_subagent_inject
        ),
    )
    task_dispatch_tool = FunctionTool(
        task_dispatch_function,
        is_read_only=False,
    )

    main_agent_factory = MainAgentFactory(
        model=model,
        tools=[
            *search_agent_factory.build_tools(),
            *trade_agent_factory.build_tools(),
            remember_preference_tool,
            forget_preference_tool,
            task_dispatch_tool,
        ],
    )

    session_store = SqlSessionStore(
        session_factory,
    )

    sessions = SessionRegistry(
        main_agent_factory=main_agent_factory,
        session_store=session_store,
    )

    conversation_store = SqlConversationStore(
        session_factory,
    )

    get_conversation_history = GetConversationHistoryUseCase(
        conversation_store=conversation_store,
    )

    orchestrator = MainAgentOrchestrator(
        sessions=sessions,
        event_bus=event_bus,
        conversation_store=conversation_store,
        preference_store=preference_store,
        preference_selector=preference_selector,
        preference_top_k=settings.preference_top_k,
    )

    return Container(
        main_agent_factory=main_agent_factory,
        search_agent_factory=search_agent_factory,
        trade_agent_factory=trade_agent_factory,
        embedder=embedder,
        vector_index=vector_index,
        knowledge_base=knowledge_base,
        event_bus=event_bus,
        conversation_store=conversation_store,
        preference_store=preference_store,
        database_engine=database_engine,
        get_conversation_history=get_conversation_history,
        sessions=sessions,
        orchestrator=orchestrator,
        product_repository=product_repository,
        order_repository=order_repository,
        catalog_search=catalog_search,
        place_order=place_order,
        query_order=query_order,
        cancel_order=cancel_order,
    )
