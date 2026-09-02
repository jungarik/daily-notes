"""Runtime adapter for invoking registered tools."""

import logging

logger = logging.getLogger(__name__)


def execute_tool(
    tool_registry: dict,
    context: dict,
    tool_name: str,
    args: dict,
    owner: str = "tool",
):
    fn = tool_registry.get(tool_name)

    if not fn:
        return "Error: unknown tool %s." % tool_name

    logger.info(
        "%s tool %s user=%s args=%s",
        owner,
        tool_name,
        context.get("user_id"),
        args,
    )

    try:
        return fn(context, args or {})
    except Exception as exc:
        logger.exception("%s tool %s failed", owner, tool_name)

        return "Error running %s: %s" % (tool_name, exc)


def execute_allowed_tool(
    tool_registry: dict,
    allowed_tools: set,
    context: dict,
    tool_name: str,
    args: dict,
    owner: str = "tool",
):
    """Execute a mandatory metadata-context tool not selected by the LLM."""
    if tool_name not in allowed_tools:
        raise ValueError("Not a metadata context tool: %s" % tool_name)

    return execute_tool(
        tool_registry,
        context,
        tool_name,
        args,
        owner,
    )
