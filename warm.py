"""Pre-fetch a race's first pages into wiki_cache/ before the session: uv run warm.py "Banana" "Napoleon"

Everyone in the room starts on the same page, so the start page and every page one click
away are the most requested. Shipping them in the cache means those clicks never reach
Wikipedia, whatever its rate limit on the venue's shared connection. Stays under the same
rate limit as the game, so a page with 400 links takes about three minutes.
"""

import sys

import wiki

if len(sys.argv) != 3:
    sys.exit('Usage: uv run warm.py "Starting page" "Target"')
start, target = sys.argv[1:]

target_title, _, _ = wiki.target_info(target)
start_title, links = wiki.links(start)
print(f"{start_title} -> {target_title}: fetching {len(links)} pages one click from the start")
failed = []
for i, title in enumerate(links, 1):
    try:
        wiki.page(title)
    except ValueError as error:  # red links and non-articles; players can't reach them either
        failed.append(f"{title}: {error}")
    print(f"\r  {i}/{len(links)}", end="", flush=True)
print(f"\nDone. {len(links) - len(failed)} pages cached in {wiki.CACHE_DIR.name}/.")
for line in failed:
    print("  skipped", line)
