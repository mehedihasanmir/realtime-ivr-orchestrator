from __future__ import annotations

import logging
import os
from typing import List, Optional, TypedDict

from google.oauth2 import service_account
from googleapiclient.discovery import build
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_google_community import CalendarToolkit
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class SchedulerState(TypedDict):
    messages: List[BaseMessage]
    final_response: str


def _load_tools(credentials_path: str):
    try:
        scopes = ["https://www.googleapis.com/auth/calendar"]
        creds = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=scopes,
        )
        service = build("calendar", "v3", credentials=creds)
        toolkit = CalendarToolkit(api_resource=service)
        return toolkit.get_tools()
    except Exception as exc:
        logger.error("Calendar setup failed: %s", exc)
        return []


class SchedulerService:
    def __init__(self, credentials_path: str, model: str) -> None:
        self.tools = _load_tools(credentials_path)
        self.llm = ChatOpenAI(model=model)
        self.llm_with_tools = self.llm.bind_tools(self.tools) if self.tools else self.llm
        self.scheduler_app = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(SchedulerState)
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", self._tool_node)

        workflow.set_entry_point("agent")
        workflow.add_conditional_edges("agent", self._should_continue)
        workflow.add_edge("tools", "agent")

        return workflow.compile()

    def _agent_node(self, state: SchedulerState):
        messages = state["messages"]
        response = self.llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def _tool_node(self, state: SchedulerState):
        messages = state["messages"]
        last_message = messages[-1]
        tool_calls = getattr(last_message, "tool_calls", None) or []

        if not tool_calls:
            return {"final_response": "No scheduling action taken."}

        if not self.tools:
            return {"final_response": "Calendar tools are not available due to setup error."}

        tool_map = {tool.name: tool for tool in self.tools}
        results = []

        for tool_call in tool_calls:
            tool_name = tool_call.get("name")
            if tool_name not in tool_map:
                results.append(f"Unknown tool: {tool_name}")
                continue

            try:
                tool_result = tool_map[tool_name].invoke(tool_call.get("args"))
                results.append(str(tool_result))
            except Exception as exc:
                results.append(f"Error: {exc}")

        combined_result = "\n".join(results)
        return {
            "messages": [HumanMessage(content=f"Tool Output: {combined_result}")],
            "final_response": "Action completed.",
        }

    def _should_continue(self, state: SchedulerState):
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None) or []
        if tool_calls:
            return "tools"
        return END

    def schedule_meeting(self, user_time_request: str) -> str:
        initial_msg = HumanMessage(
            content=(
                "User request: '"
                + user_time_request
                + "'. Check for conflicts first. If free, book it. If busy, suggest a time."
            )
        )
        result = self.scheduler_app.invoke({"messages": [initial_msg]})
        return result["messages"][-1].content


_scheduler_service: Optional[SchedulerService] = None


def _get_scheduler_service() -> SchedulerService:
    global _scheduler_service
    if _scheduler_service is None:
        settings = get_settings()
        model = os.getenv("OPENAI_SCHEDULER_MODEL", "gpt-4o")
        _scheduler_service = SchedulerService(settings.google_credentials_path, model)
    return _scheduler_service


def schedule_meeting_tool(user_time_request: str) -> str:
    scheduler = _get_scheduler_service()
    return scheduler.schedule_meeting(user_time_request)
