from agentscope.agent import Agent
from agentscope.permission import (
    PermissionBehavior,
    PermissionRule,
)


_AUTO_ALLOWED_BUSINESS_TOOLS = (
    "place_order_tool",
    "cancel_order_tool",
    "task_dispatch",
)


def allow_business_tools(
    agent: Agent,
) -> Agent:
    allow_rules = (
        agent.state.permission_context.allow_rules
    )

    for tool_name in _AUTO_ALLOWED_BUSINESS_TOOLS:
        rules = allow_rules.setdefault(
            tool_name,
            [],
        )

        already_configured = any(
            rule.source == "projectSettings"
            for rule in rules
        )

        if already_configured:
            continue

        rules.append(
            PermissionRule(
                tool_name=tool_name,
                rule_content=None,
                behavior=PermissionBehavior.ALLOW,
                source="projectSettings",
            )
        )

    return agent
