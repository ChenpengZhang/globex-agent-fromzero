from dataclasses import dataclass

from agentscope.agent import Agent
from agentscope.tool import FunctionTool

from app.application.agents.main_agent import create_main_agent
from app.application.tools.product_search_tool import (
    build_product_search_tool,
)
from app.application.usecases.catalog_search import (
    CatalogSearchUseCase,
)
from app.domain.catalog.ports.product_repository import (
    ProductRepository,
)
from app.infrastructure.llm import create_chat_model
from app.infrastructure.persistence.in_memory_product_repository import (
    InMemoryProductRepository,
)
from app.infrastructure.persistence.seed_products import (
    build_seed_products,
)
from app.infrastructure.settings import load_settings


@dataclass
class Container:
    main_agent: Agent
    product_repository: ProductRepository
    catalog_search: CatalogSearchUseCase
    # The container is the only place where it knows every module


def build_container() -> Container:
    settings = load_settings()

    product_repository = InMemoryProductRepository(
        build_seed_products(),
    )

    catalog_search = CatalogSearchUseCase(
        product_repository,
    )

    product_search_function = build_product_search_tool(
        catalog_search,
    )

    product_search_tool = FunctionTool(
        product_search_function,
        is_read_only=True,
    )

    model = create_chat_model(settings)

    main_agent = create_main_agent(
        model=model,
        tools=[
            product_search_tool,
        ],
    )

    return Container(
        main_agent=main_agent,
        product_repository=product_repository,
        catalog_search=catalog_search,
    )