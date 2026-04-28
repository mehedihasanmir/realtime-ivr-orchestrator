from __future__ import annotations

import os
from typing import TypedDict

from dotenv import load_dotenv
from langgraph.graph import StateGraph, END

from app.services.scraper import scrape_website
from app.services.twilio_calls import initiate_call

load_dotenv()


class AgentState(TypedDict):
    url: str
    phone_number: str
    scraped_content: str
    call_sid: str


# ------------------------------------------------------------------
# Graph nodes
# ------------------------------------------------------------------

def scrape_node(state: AgentState) -> AgentState:
    return {"scraped_content": scrape_website(state["url"])}


def call_node(state: AgentState) -> AgentState:
    return {"call_sid": initiate_call(state["phone_number"], state["scraped_content"])}


# ------------------------------------------------------------------
# Graph definition
# ------------------------------------------------------------------

_workflow = StateGraph(AgentState)
_workflow.add_node("scraper", scrape_node)
_workflow.add_node("caller", call_node)
_workflow.set_entry_point("scraper")
_workflow.add_edge("scraper", "caller")
_workflow.add_edge("caller", END)

scraper_app = _workflow.compile()


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    target_url = os.getenv("TARGET_URL", "https://www.wikipedia.org/")
    target_phone = os.getenv("TARGET_PHONE", "+8801771469627")

    result = scraper_app.invoke({"url": target_url, "phone_number": target_phone})
    print(f"Call initiated — SID: {result.get('call_sid')}")
