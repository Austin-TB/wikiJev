# Wikirace with Jev

Race across Wikipedia in your browser: start on one article and reach a target by clicking links
inside the article, in as few clicks as you can. First you play by hand. Later in the session you
hand the clicking to Jev, TypeSafe's model, and change how it decides.

## Set up

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python for you
if needed) and a TypeSafe API key from [console.typesafe.ai](https://console.typesafe.ai).

```sh
cp .env.example .env
```

Open `.env` and:

- put your key after `TYPESAFE_API_KEY=`
- delete the `WIKIPEDIA_CONTACT` line. The app asks for your name and email the first time you open it.

Wikipedia's API policy asks every app to say who is sending its requests. Without contact details it
allows only 10 requests a minute. Your name and email are saved in `.env` and go only to Wikipedia.

## Play by hand

```sh
uv run server.py
```

Open <http://localhost:8000>. The first run installs the Python packages, so it can take a minute.
Pick a starting page and a target (try Banana → Napoleon), then click links inside the article until
you reach the target. The server listens on your laptop only, because it uses your TypeSafe key.

## Play with Jev

Later in the session, copy Jev's decision file into this folder:

```sh
cp handout/decide.py .
```

Reload the page and **Play with Jev** appears. Jev races the same pages while you watch each click,
with the links it rated highest. The server picks up your edits to `decide.py` on the next race, so
you don't need to restart it.

Or from the command line:

```sh
uv run race.py                        # six sample races, then a score
uv run race.py "Banana" "Napoleon"    # one race
```

## How Jev decides

`decide.py` is the only file about Jev. Its one function,

```python
choose_link(target, target_summary, current_page, links) -> dict[str, float]
```

gets the situation as plain text and up to 255 link titles, and returns a probability for each
link. Inside are three commented steps: build the context, list the options, ask one Choice
question.

Everything else is in `race.py`: loading pages, skipping pages already visited, spotting a link
that leads straight to the target, and splitting pages with more than 255 links into groups. So you
can change how Jev thinks without breaking the game.

## Things to try in `decide.py`

- Reword `INSTRUCTIONS`. It asks which link is most closely *related* to the target, not which one
  gets there *fastest*. Try asking the second question and compare.
- Take the target's summary out of the context, or describe the target in your own words.
- Remove Jev entirely: return the same probability for every link
  (`{link: 1 / len(links) for link in links}`) and see how far a race gets.

After each change, run `uv run race.py` and compare the last line: races won out of six, average
clicks, and time per decision.

## Files

| File | What it does |
| --- | --- |
| `handout/decide.py` | Jev's decision. The file you copy and edit. |
| `race.py` | The race loop, shared by the page and the command line. |
| `wiki.py`, `article.py`, `wiki_titles.py` | Wikipedia pages, and the rules for which links count. |
| `server.py`, `index.html` | The browser app. |
| `warm.py` | Fetches a race's first pages ahead of time: `uv run warm.py "Banana" "Napoleon"`. |
| `wiki_cache/` | Pages already fetched, so repeat races are fast and spare Wikipedia. |
