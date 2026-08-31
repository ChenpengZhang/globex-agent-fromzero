from app.domain.catalog.money import Money
from app.domain.catalog.product import Product
from app.domain.catalog.sku import Sku


def build_seed_products() -> list[Product]:
    return [
        Product(
            product_id="P1001",
            title="Nomadica 旅行三件套",
            brand="Nomadica",
            category="旅行装备",
            origin_country="VN",
            description="包含收纳袋、颈枕和眼罩，轻便耐用，适合长途旅行。",
            ships_to=["CN", "US", "SG"],
            skus=[
                Sku(
                    sku_id="P1001-S1",
                    spec="军绿色",
                    price=Money.from_major_units(189, "CNY"),
                    stock=50,
                ),
                Sku(
                    sku_id="P1001-S2",
                    spec="沙漠黄",
                    price=Money.from_major_units(199, "CNY"),
                    stock=30,
                ),
            ],
        ),
        Product(
            product_id="P1002",
            title="TrailOx 20寸登机箱",
            brand="TrailOx",
            category="旅行装备",
            origin_country="DE",
            description="铝框登机箱，结实抗摔，配备万向静音轮。",
            ships_to=["CN", "US", "EU"],
            skus=[
                Sku(
                    sku_id="P1002-S1",
                    spec="银色 / 20寸",
                    price=Money.from_major_units(899, "CNY"),
                    stock=20,
                ),
            ],
        ),
        Product(
            product_id="P1003",
            title="Wanderlite 折叠旅行双肩包",
            brand="Wanderlite",
            category="旅行装备",
            origin_country="KR",
            description="35L 防泼水双肩包，轻便、可折叠，适合旅行和通勤。",
            ships_to=["CN", "JP", "SG"],
            skus=[
                Sku(
                    sku_id="P1003-S1",
                    spec="黑色 / 35L",
                    price=Money.from_major_units(259, "CNY"),
                    stock=40,
                ),
            ],
        ),
    ]