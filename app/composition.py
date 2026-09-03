from dataclasses import dataclass

from agentscope.tool import FunctionTool

from app.application.agents.main_agent import MainAgentFactory
from app.application.agents.orchestrator import (
    MainAgentOrchestrator,
)
from app.application.tools.product_search_tool import (
    build_product_search_tool,
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
    sessions: SessionRegistry
    orchestrator: MainAgentOrchestrator

    product_repository: ProductRepository
    order_repository: OrderRepository

    catalog_search: CatalogSearchUseCase
    place_order: PlaceOrderUseCase
    query_order: QueryOrderUseCase
    cancel_order: CancelOrderUseCase
    # The container is the only place where it knows every module


def build_container() -> Container:
    settings = load_settings()

    product_repository = InMemoryProductRepository(
        build_seed_products(),
    )

    catalog_search = CatalogSearchUseCase(
        product_repository,
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

    product_search_function = build_product_search_tool(
        catalog_search,
    )

    product_search_tool = FunctionTool(
        product_search_function,
        is_read_only=True,
    )

    model = create_chat_model(settings)

    main_agent_factory = MainAgentFactory(
        model=model,
        tools=[
            product_search_tool,
        ],
    )

    sessions = SessionRegistry(
        main_agent_factory=main_agent_factory,
    )

    orchestrator = MainAgentOrchestrator(
        sessions=sessions,
    )

    return Container(
        main_agent_factory=main_agent_factory,
        sessions=sessions,
        orchestrator=orchestrator,
        product_repository=product_repository,
        order_repository=order_repository,
        catalog_search=catalog_search,
        place_order=place_order,
        query_order=query_order,
        cancel_order=cancel_order,
    )
