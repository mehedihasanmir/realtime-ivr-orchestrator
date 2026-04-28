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


def scrape_website_node(state: AgentState):
    text_content = scrape_website(state["url"])
    return {"scraped_content": text_content}


def initiate_call_node(state: AgentState):
    call_sid = initiate_call(state["phone_number"], state["scraped_content"])
    return {"call_sid": call_sid}


workflow = StateGraph(AgentState)
workflow.add_node("scraper", scrape_website_node)
workflow.add_node("caller", initiate_call_node)

workflow.set_entry_point("scraper")
workflow.add_edge("scraper", "caller")
workflow.add_edge("caller", END)

app_scraper = workflow.compile()


if __name__ == "__main__":
    target_url = os.getenv("TARGET_URL", "https://www.wikipedia.org/")

    # Example format: +880...
    target_phone = os.getenv("TARGET_PHONE", "+8801771469627")

    app_scraper.invoke(
        {
            "url": target_url,
            "phone_number": target_phone,
        }
    )
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


def scrape_website_node(state: AgentState):
    text_content = scrape_website(state["url"])
    return {"scraped_content": text_content}


def initiate_call_node(state: AgentState):
    call_sid = initiate_call(state["phone_number"], state["scraped_content"])
    return {"call_sid": call_sid}

workflow = StateGraph(AgentState)
workflow.add_node("scraper", scrape_website_node)
workflow.add_node("caller", initiate_call_node)

workflow.set_entry_point("scraper")
workflow.add_edge("scraper", "caller")
workflow.add_edge("caller", END)

app_scraper = workflow.compile()

# --- EXECUTION ---
if __name__ == "__main__":
    target_url = os.getenv("TARGET_URL", "https://www.wikipedia.org/")

    # Example format: +880...
    target_phone = os.getenv("TARGET_PHONE", "+8801771469627")

    app_scraper.invoke({
        "url": target_url,
        "phone_number": target_phone,
    })