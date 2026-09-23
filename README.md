# Wikirace with Jev

You raced across Wikipedia in the room. Here you watch Jev, TypeSafe's model, race on your own
laptop: pick a start and a target, press Go, and see which links Jev weighs on every page and
which one it clicks. Then change how Jev decides, in `decide.py`, and race again.

## Set up

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs Python for
you if needed, and a TypeSafe API key from [console.typesafe.ai](https://console.typesafe.ai).

In this folder, run:

```sh
cp .env.example .env
```

On Windows, run `copy .env.example .env` instead. Then open `.env` and fill in both lines:

- `TYPESAFE_API_KEY=`: your key.
- `WIKIPEDIA_CONTACT=`: your name and email, in place of `Your Name; you@example.com`. Wikipedia's
  API policy asks every app to say who is sending its requests. Your details go only to Wikipedia.

## Run

```sh
uv run server.py
```

Open <http://localhost:8000> and press **Go**. The first run installs the Python packages, so it
can take a minute. The server listens on your laptop only, because it uses your TypeSafe key.

Each page Jev lands on appears as a card. It shows how many links Jev chose from, how long Jev
and Wikipedia took, and the five links Jev rated highest, with its pick highlighted. When a page
links straight to the target, the app clicks it without asking Jev.

## How Jev decides

`decide.py` is the only file about Jev. Its one function,

```python
choose_link(target, target_summary, current_page, links) -> dict[str, float]
```

gets the situation as plain text and up to 255 link titles, and returns each link's probability
of being the best next click. It works in three commented steps:

1. **Context**: the target's title and summary, and the page Jev is on.
2. **Options**: the link titles to choose from.
3. **Question**: one Choice question, `INSTRUCTIONS`, asking which link is most closely related
   to the target. Jev answers with a probability for every link.

The app does everything around it, in `race.py` and `wiki.py`. It fetches each page and keeps
only the links you could click in the room: links in the article text, not in navigation boxes
or reference lists. It skips pages Jev has already visited and clicks the target itself when a
page links to it. A page with more than 255 links is split into groups, and Jev then chooses
between the best five of each group. So you can change how Jev thinks without breaking the race.

## Things to try in `decide.py`

- Reword `INSTRUCTIONS`. It asks which link is most closely *related* to the target, not which one
  gets there *fastest*. Try asking the second question and compare.
- Take the target's summary out of the context, or describe the target in your own words.
- Remove Jev entirely: return the same probability for every link
  (`{link: 1 / len(links) for link in links}`) and see how far a race gets.

Save the file and press **Go** again. The server picks up your edit without a restart.

## From the command line

```sh
uv run race.py                        # six sample races, then a score
uv run race.py "Banana" "Napoleon"    # one race
```

The last line of the sample run is the quickest way to compare two versions of `decide.py`: races
won out of six, average clicks, and time per decision. Jev's close calls can go either way from
one run to the next, so run it twice before trusting a small difference.

## Files

| File | What it does |
| --- | --- |
| `decide.py` | Jev's decision. The file you edit. |
| `race.py` | The race loop, shared by the page and the command line. |
| `wiki.py` | Wikipedia pages, and the rules for which links count. |
| `server.py`, `index.html` | The page at localhost:8000. |
| `wiki_cache/` | Pages already fetched, so repeat races are fast and spare Wikipedia. |
