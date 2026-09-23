"""Run a Wikipedia race: uv run race.py "Banana" "Napoleon"  (no arguments runs a sample set).

`race()` yields an event per step, so the command line and the web page share one loop.
Jev's decision comes from `choose_link` in decide.py. Everything else is here: pages, loop
avoidance, the exact target check, and pages with more links than one Jev question can hold.
"""

import math
import sys
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor

import wiki

MAX_HOPS = 15
MAX_OPTIONS = 255  # options one Jev Choice question can hold
FINALISTS = 5      # links each group sends to the final round on pages with more links than that

SAMPLES = [
    ("Banana", "Napoleon"),
    ("Pizza", "Albert Einstein"),
    ("Lego", "Julius Caesar"),
    ("Kangaroo", "Quantum mechanics"),
    ("Taylor Swift", "Photosynthesis"),
    ("Chess", "Vincent van Gogh"),
]

ChooseLink = Callable[[str, str, str, list[str]], dict[str, float]]


def rank_links(choose_link: ChooseLink, target: str, summary: str, page: str,
               links: list[str]) -> tuple[list[tuple[str, float]], int]:
    """Rank `links` best first, and count the Jev calls it took.

    A page with more than 255 links runs as a tournament: its links are split into groups
    that Jev ranks at the same time, then the best of each group meet in one final call.
    """
    calls = 0
    while len(links) > 1:
        n_groups = math.ceil(len(links) / MAX_OPTIONS)
        size = math.ceil(len(links) / n_groups)
        groups = [links[i:i + size] for i in range(0, len(links), size)]
        with ThreadPoolExecutor(len(groups)) as pool:
            answers = list(pool.map(lambda group: choose_link(target, summary, page, group), groups))
        calls += len(groups)
        rankings = [sorted(answer.items(), key=lambda kv: -kv[1]) for answer in answers]
        if len(groups) == 1:
            return rankings[0], calls
        links = [title for ranking in rankings for title, _ in ranking[:FINALISTS]]
    return [(links[0], 1.0)], calls


def race(start: str, target: str, choose_link: ChooseLink) -> Iterator[dict]:
    """Yield {"type": "target"}, then one {"type": "hop"} per click, then {"type": "done"}."""
    target_title, target_names, summary = wiki.target_info(target)
    yield {"type": "target", "title": target_title, "summary": summary}

    path, visited = [], set()
    jev_s = wiki_s = 0.0
    decisions = 0
    page = start
    t_start = time.perf_counter()

    while len(path) <= MAX_HOPS:
        t = time.perf_counter()
        page, links = wiki.links(page)
        wiki_ms = (time.perf_counter() - t) * 1000
        wiki_s += wiki_ms / 1000
        path.append(page)
        visited.add(page)
        hop = {"type": "hop", "n": len(path), "page": page, "wiki_ms": round(wiki_ms)}

        # Exact checks stay in code: no model needed to spot the target.
        if page in target_names:
            break
        if any(link in target_names for link in links):
            yield hop | {"pick": target_title, "by": "code"}
            path.append(target_title)
            break

        candidates = [link for link in links if link not in visited]
        # Disambiguation pages list unrelated namesakes, so they are a last resort.
        candidates = [link for link in candidates if not link.endswith("(disambiguation)")] or candidates
        if not candidates:
            yield hop | {"pick": None, "by": "dead end"}
            break

        t = time.perf_counter()
        ranking, calls = rank_links(choose_link, target_title, summary, page, candidates)
        jev_ms = (time.perf_counter() - t) * 1000
        jev_s += jev_ms / 1000
        decisions += 1
        yield hop | {"pick": ranking[0][0], "by": "jev", "links": len(candidates), "calls": calls,
                     "jev_ms": round(jev_ms), "top": [[title, round(p, 4)] for title, p in ranking[:5]]}
        page = ranking[0][0]

    yield {"type": "done", "won": path[-1] == target_title, "path": path, "clicks": len(path) - 1,
           "total_s": round(time.perf_counter() - t_start, 2), "jev_s": round(jev_s, 2),
           "wiki_s": round(wiki_s, 2), "decisions": decisions}


def print_race(start: str, target: str, choose_link: ChooseLink) -> dict:
    for event in race(start, target, choose_link):
        match event:
            case {"type": "target"}:
                print(f"\n=== {start} -> {event['title']} ===")
            case {"type": "hop", "by": "jev"}:
                alts = ", ".join(f"{title} {p:.2f}" for title, p in event["top"][1:3])
                print(f"  {event['n']:>2}. {event['page']}  [{event['links']} links, {event['calls']} "
                      f"call{'s' * (event['calls'] > 1)}, {event['jev_ms']} ms]  -> {event['pick']} "
                      f"({event['top'][0][1]:.2f})   next: {alts}")
            case {"type": "hop"}:
                print(f"  {event['n']:>2}. {event['page']}  -> {'target link on page' if event['pick'] else 'dead end'}")
            case {"type": "done"}:
                print(f"  {'WON' if event['won'] else 'LOST'} in {event['clicks']} clicks | total {event['total_s']}s | "
                      f"jev {event['jev_s']}s over {event['decisions']} decisions | wikipedia {event['wiki_s']}s")
                return event


if __name__ == "__main__":
    from decide import choose_link
    pairs = [tuple(sys.argv[1:3])] if len(sys.argv) == 3 else SAMPLES
    results = [print_race(start, target, choose_link) for start, target in pairs]
    if len(results) > 1:
        wins = [r for r in results if r["won"]]
        decisions = sum(r["decisions"] for r in results)
        print(f"\n{len(wins)}/{len(results)} won | avg clicks (wins) "
              f"{sum(r['clicks'] for r in wins) / max(len(wins), 1):.1f} | "
              f"avg jev per decision {sum(r['jev_s'] for r in results) / max(decisions, 1) * 1000:.0f} ms")
