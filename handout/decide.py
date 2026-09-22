"""Jev's part of the Wikipedia race: which link do we click next?

The app does everything else: it fetches pages, runs the race, avoids loops and spots
the target. This file only turns the current situation into a question for Jev and
hands back Jev's answer.
"""

from dotenv import load_dotenv
from typesafe_sdk import Choice, TypeSafeClient

load_dotenv()
client = TypeSafeClient()  # uses TYPESAFE_API_KEY from .env

# Ask how related each link is, not which one reaches the target fastest: that would be
# multi-hop reasoning, a documented weak spot. The app's loop does the multi-hop part.
INSTRUCTIONS = (
    "We are playing a Wikipedia race toward the article `target.title` (described in `target.summary`). "
    "Which of these linked articles is most closely related to `target.title`?"
)


def choose_link(target: str, target_summary: str, current_page: str, links: list[str]) -> dict[str, float]:
    """Return each link's probability of being the best next click. Takes at most 255 links."""
    # 1. Context: what Jev needs to know about the situation.
    context = {
        "target": {"title": target, "summary": target_summary},
        "current_page": current_page,
    }

    # 2. Options: the links Jev can choose from. Titles speak for themselves, so no descriptions.
    options = dict.fromkeys(links)

    # 3. Ask one Choice question. Jev returns a probability for every option.
    result = client.system_one(
        state=context,
        questions={"next_link": Choice(instructions=INSTRUCTIONS, criteria=options)},
    )
    return result.choices["next_link"].probabilities
