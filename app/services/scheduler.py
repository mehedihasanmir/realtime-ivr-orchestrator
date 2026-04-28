from __future__ import annotations

import logging
import os
import threading
from typing import List, Optional, TypedDict

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_google_community import CalendarToolkit
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

from app.core.config import get_settings
from app.services.google_oauth import SCOPES, TokenStore

logger = logging.getLogger(__name__)

class SchedulerState(TypedDict):
    messages: List[BaseMessage]


# ------------------------------------------------------------------
# Calendar tool loader
# ------------------------------------------------------------------

def _load_calendar_tools(credentials: Credentials) -> list:
    try:
        service = build("calendar", "v3", credentials=credentials)
        toolkit = CalendarToolkit(api_resource=service)
        return toolkit.get_tools()
    except Exception as exc:
        logger.error("Calendar tool setup failed: %s", exc)
        return []


# ------------------------------------------------------------------
# Scheduler service
# ------------------------------------------------------------------

class SchedulerService:
    """LangGraph-based meeting scheduler backed by Google Calendar."""

    def __init__(self, model: str, token_store: TokenStore) -> None:
        self.model = model
        self.token_store = token_store
        self.tools: list = []
        self.tool_map: dict = {}
        self.llm_with_tools = ChatOpenAI(model=model)
        self._graph = self._build_graph()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self):
        workflow = StateGraph(SchedulerState)
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", self._tool_node)

        workflow.set_entry_point("agent")
        workflow.add_conditional_edges("agent", self._router)
        workflow.add_edge("tools", "agent")

        return workflow.compile()

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def _agent_node(self, state: SchedulerState) -> SchedulerState:
        response: AIMessage = self.llm_with_tools.invoke(state["messages"])
        return {"messages": state["messages"] + [response]}

    def _tool_node(self, state: SchedulerState) -> SchedulerState:
        last_message: AIMessage = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None) or []

        if not tool_calls:
            return {"messages": state["messages"]}

        if not self.tool_map:
            tool_messages = []
            for tool_call in tool_calls:
                tool_call_id = tool_call.get("id") or tool_call.get("tool_call_id")
                if not tool_call_id:
                    logger.warning("Tool call missing id: %s", tool_call)
                    tool_call_id = "missing_tool_call_id"
                tool_messages.append(
                    ToolMessage(
                        content="Calendar tools are unavailable due to a setup error.",
                        tool_call_id=tool_call_id,
                    )
                )
            return {"messages": state["messages"] + tool_messages}

        tool_messages: List[ToolMessage] = []
        for tool_call in tool_calls:
            tool_name = tool_call.get("name")
            tool = self.tool_map.get(tool_name)
            tool_call_id = tool_call.get("id") or tool_call.get("tool_call_id")
            if not tool_call_id:
                logger.warning("Tool call missing id: %s", tool_call)
                tool_call_id = "missing_tool_call_id"
            if tool is None:
                tool_messages.append(
                    ToolMessage(
                        content=f"Error: unknown tool requested: {tool_name!r}",
                        tool_call_id=tool_call_id,
                    )
                )
                continue
            try:
                result = tool.invoke(tool_call.get("args", {}))
                tool_messages.append(
                    ToolMessage(content=str(result), tool_call_id=tool_call_id)
                )
            except Exception as exc:
                logger.exception("Tool %r raised an error: %s", tool_name, exc)
                tool_messages.append(
                    ToolMessage(
                        content=f"Error running {tool_name!r}: {exc}",
                        tool_call_id=tool_call_id,
                    )
                )

        return {"messages": state["messages"] + tool_messages}

    # ------------------------------------------------------------------
    # Router
    # ------------------------------------------------------------------

    @staticmethod
    def _router(state: SchedulerState) -> str:
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None) or []
        return "tools" if tool_calls else END

    # ------------------------------------------------------------------
    # Public method
    # ------------------------------------------------------------------

    def schedule_meeting(self, user_time_request: str, user_id: Optional[str] = None) -> str:
        credentials = self._resolve_credentials(user_id)
        if not credentials:
            return (
                "No Google Calendar connection for this user. "
                "Visit /auth/google/start?user_id=YOUR_ID to connect."
            )

        tools = _load_calendar_tools(credentials)
        if not tools:
            return "Calendar tools are unavailable due to a setup error."

        with self._lock:
            self._configure_tools(tools)
            initial_msg = HumanMessage(
                content=(
                    f"User request: '{user_time_request}'. "
                    "Check for scheduling conflicts first. "
                    "If the slot is free, book it. "
                    "If it is busy, suggest an alternative time."
                )
            )
            final_state = self._graph.invoke({"messages": [initial_msg]})
            last = final_state["messages"][-1]
            return last.content if hasattr(last, "content") else str(last)

    def _configure_tools(self, tools: list) -> None:
        self.tools = tools
        self.tool_map = {tool.name: tool for tool in tools}
        llm = ChatOpenAI(model=self.model)
        self.llm_with_tools = llm.bind_tools(self.tools) if self.tools else llm

    def _resolve_credentials(self, user_id: Optional[str]) -> Optional[Credentials]:
        if not user_id:
            return None
        creds = self.token_store.get_credentials(user_id)
        if not creds:
            return None
        return self.token_store.refresh_credentials(user_id, creds)
        


# ------------------------------------------------------------------
# Thread-safe singleton
# ------------------------------------------------------------------

_lock = threading.Lock()
_scheduler_service: Optional[SchedulerService] = None


def _get_scheduler_service() -> SchedulerService:
    global _scheduler_service
    if _scheduler_service is None:
        with _lock:
            if _scheduler_service is None:
                settings = get_settings()
                model = os.getenv("OPENAI_SCHEDULER_MODEL", "gpt-4o")
                token_store = TokenStore(settings.google_oauth_token_path)
                _scheduler_service = SchedulerService(model, token_store)
    return _scheduler_service


def schedule_meeting_tool(user_time_request: str, user_id: Optional[str] = None) -> str:
    """Top-level callable passed to RealtimeBridge."""
    return _get_scheduler_service().schedule_meeting(user_time_request, user_id)
