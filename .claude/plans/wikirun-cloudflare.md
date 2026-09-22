# WikiRoutes for a 100-player room: Node server behind a Cloudflare named tunnel

Plan written 2026-09-22 for the AIC hands-on session. Updates the sibling project `../wikirun`.
Replaces the earlier Workers + Durable Objects version of this plan.
`[x]` is done, `[ ]` is still to do.

## The goal

Everyone in the room plays the same Wikipedia race on their own phone or laptop, over their own
internet, by opening `https://race.<domain>`. Their browser fetches articles straight from
Wikipedia under their own name and email; only clicks and results go to our server. A live
leaderboard runs on the big screen, and Jev joins the same room as a player, under the same rules,
so its result lands on the same board.

wikirun's Node server stays. It runs on the presenter's Mac and is published at `race.<domain>`
through a named Cloudflare Tunnel. Two things change underneath: the server stops fetching a page
for every click, and it stops sending the whole room to every player on every change.

## Decisions made (say if any is wrong)

1. **Named tunnel on your Cloudflare domain.** `cloudflared` on the Mac holds an outbound
   connection to Cloudflare, which serves `race.<domain>` with HTTPS. No open ports. Quick tunnels
   (try.cloudflare.com) are for spikes and rehearsals only: Cloudflare documents them as "for
   testing only", with "a 200 concurrent request limit" and no Server-Sent Events, and the address
   changes whenever `cloudflared` restarts.
2. **Players fetch Wikipedia in their own browser.** Checked live on 2026-09-21: the API allows
   anonymous cross-origin requests (`origin=*`) and the `Api-User-Agent` header, which Wikimedia's
   User-Agent policy names as the way browser apps identify themselves. The player's email goes
   in that header and in `localStorage`, never to our server.
3. **The server still talks to Wikipedia, but rarely.** It keeps its rate-limited client
   (`server/wiki.js`) for the host's search, choosing and checking a round's pages, the target's
   redirect names at round start, and verifying finished paths. The picker and its rules stay
   exactly as they are.
4. **Small messages, measured.** Today one `room:state` with 100 players is 11 KB, and every click
   sends it to every socket: 1.1 MB per click, 11 MB/s at 10 clicks a second, and 38 MB of
   broadcasts while 100 people join. All of it leaves through the Mac's connection. New protocol:
   the full state goes only to a socket that joins or reconnects, and to everyone when the phase
   changes. Clicks, joins and leaves go out as small updates (a click is 72 bytes), batched to at
   most two messages a second: about 72 KB/s at 10 clicks a second.
5. **Static files from Cloudflare's edge.** Each player loads 146 KB (index, app, styles, fonts,
   Socket.IO client): 14.6 MB for the room. Scripts, styles and fonts get
   `Cache-Control: public, max-age=86400` with a version in the URL, so Cloudflare caches them and
   the Mac serves each one about once per Cloudflare location. The Socket.IO client is copied into
   `public/vendor/` so it follows the same rule. HTML stays uncached (10 KB each).
6. **A round ends at the time limit or when the host ends it, not at the first arrival.** With 100
   players, ending everyone's round when one person finishes would be a poor experience. Finishers
   rank by moves, then seconds on the server's clock. Round points 10/7/5/3/2/1 for the top six;
   the party standings add them up. (Today: first arrival wins the round and scores 1 point.)
7. **Clicks are reported live.** The client sends `{clicked, landed}` for each click: the link
   title it followed and the page it landed on after redirects. The server keeps the path, so moves
   stay server-side and Back and Forward keep today's rules. The board shows everyone's moves live.
8. **Verification is best effort, after a player finishes.** Two Wikipedia requests check a whole
   path: `prop=links` with `pltitles=<clicked titles>` confirms each link exists on the page before
   it, and `redirects=1` confirms each clicked title resolves to the page landed on. Fixture:
   Banana → Augustus → Napoleon, where Augustus links "Napoleon Bonaparte", a redirect. Verified
   finishes get a tick; a failed or skipped check shows "unverified" and never blocks the board.
   Known gap: `prop=links` includes navbox and "See also" links that players never see, so the check
   accepts a few links our pages hide. Fine for a fun leaderboard.
9. **Spectator board.** `/?room=CODE&view=board` joins without a player row: standings, live moves
   and results, sized for a projector.
10. **Jev is a player.** A Python bot joins over Socket.IO, flagged `bot: true` so its row gets a
    badge. It lives in AIC-HandsOn and reuses that project's `race.py`, `wiki.py` and `article.py`,
    which already follow wikirun's article rules (same 210 links on the Tuff fixture).
11. **Player cap becomes a setting**, `MAX_PLAYERS`, default 150 (today it is hard-coded to 12).
12. **The Mac is the server.** Rooms live in memory, so a crash, sleep or lost connection ends the
    room. Accepted for a one-hour session: keep it plugged in, run `caffeinate`, give it a reliable
    connection, and keep The Wiki Game's private group as the fallback.

## The Jev part: one file for the hands-on

Jev's decision lives in one file, `AIC-HandsOn/handout/decide.py` (38 lines). It is the file
attendees receive, read and edit, and every consumer calls it the same way: the solo app's
"Play with Jev", the `race.py` command line, and the wikirun bot in Phase 4. The rest of each app
can change freely without touching it.

```python
choose_link(target: str, target_summary: str, current_page: str, links: list[str]) -> dict[str, float]
```

- In: plain facts about the situation and at most 255 link titles. Out: each link's probability.
- Inside, three commented steps: build the context, list the options, ask one Choice question.
- No pages, no loop, no game rules, no SDK types in or out.
- The app does the rest in `race.py`: loop avoidance, dropping disambiguation pages, the exact
  target check, and pages with more than 255 links (split into groups asked in parallel, then a
  final call on the top five of each group).

Checked on 2026-09-22 after moving to this interface: the six sample races still win 6/6 with 2.8
clicks on average; a decision takes about 340 ms on a warm connection and 0.7–1.2 s on pages
with 400–600 links.

## To confirm before Phase 2

- [ ] Scoring: ranked finishes with 10/7/5/3/2/1 points, or keep "first arrival wins"?
- [ ] Rounds per party for the session: 2 (today's default is 5; it stays a setting).
- [ ] Subdomain, e.g. `race.<domain>`.
- [ ] Round time limit choices stay 1/2/3/5/10 minutes.

## Architecture

```
Player's phone (own internet)                    Presenter's Mac
─────────────────────────────                    ─────────────────────────────────────────
https://race.<domain>  ── Cloudflare edge ──►    cloudflared (named tunnel, outbound only)
  static files cached at the edge                  │
                                                   ▼
public/app.js (Socket.IO client)         ◄──►    Node server on 127.0.0.1:3000
  fetch pages from en.wikipedia.org                 server/room.js  rooms in memory, no page fetching
  (origin=*, Api-User-Agent: name; email)           server/wiki.js  search, picker, target redirects,
  render with public/article.js                                     verification (≤150 requests/min)
  (DOMParser + DOMPurify, same rules)               server/verify.js  2 requests per finisher
  send nav:go {clicked, landed}          ──►        updates to all sockets, batched ≤ 2/s

Big screen: ?view=board (no player row)
Presenter: bot.py (Jev, in AIC-HandsOn) ──►       same protocol, bot: true
```

Wikipedia load per round with 100 players: every page view comes from the players' own
connections; the server makes about 10 requests to set up the round and about 200 to verify the
finishers, spread over the results screen.

## Changes by file (in `../wikirun`)

Server:
- `server/room.js` — `go`, `back`, `forward` and `viewFor` no longer fetch pages. `go` takes
  `{clicked, landed}`, normalizes both, and records the hop. Ranked finishes; the round ends at the
  time limit or on the host's `round:end`. Target redirect names come from `wiki.lookup` at round
  start and decide `won`. `MAX_PLAYERS` from settings. Two outputs instead of one: `publish(event,
  payload)` for small updates and `#changed()` for phase changes. After a finish, calls verification
  and publishes the verdict.
- `server/nav.js` — each path entry keeps the link that led to it (`{title, via}`), so a finished
  path can be verified. Moves and Back/Forward rules unchanged.
- `server/verify.js` (new) — the two-request check through the existing `createApi` limiter.
  Chunks `titles` and `pltitles` at 50. Gives up quietly on 429.
- `server/app.js` — new events `round:end` (host) and `room:watch` (board); `nav:go` payload
  change; update batching (≤ 2 messages a second per room); static routes for the new client
  modules and `vendor/`; cache headers from decision 5; CSP `connect-src 'self' ws: wss:
  https://en.wikipedia.org`.
- `server/config.js` — `MAX_PLAYERS`. `HOST=127.0.0.1` when tunnelled (cloudflared connects
  locally). `PUBLIC_URL=https://race.<domain>` already drives the join link and QR code.
- `server/article.js` — unchanged; the picker still uses it to check a start page does not link
  straight to the target.

Client:
- `public/article.js` (new) — browser twin of `server/article.js`: `DOMParser` in place of cheerio,
  DOMPurify in place of sanitize-html, the same allowlists, `wr-` id prefix and `data-title` links.
  Imports `server/titles.js`, which is plain ES and is served as `/titles.js`.
- `public/wiki.js` (new) — `origin=*`, `Api-User-Agent`, an in-memory page cache so Back and
  Forward never refetch, and a visible "Wikipedia asked us to slow down…" wait on 429 that honours
  `Retry-After`.
- `public/app.js` — becomes an ES module. Email field next to the name on the home screen, with a
  line saying it goes only to Wikipedia. Fetches and renders pages itself; sends `nav:go
  {clicked, landed}`. Applies small updates to its copy of the state. HUD race list shows the top 5
  plus you; results and standings show the top 10 plus you, with paths on tap. Board view.
- `public/index.html` — module script tag, email field, board markup.
- `public/vendor/` — `purify.min.js` and `socket.io.min.js`, with their licences.

Tests and tools:
- `test/article.test.js` — runs the browser `article.js` under jsdom (dev dependency) and asserts
  the link list on `test/fixtures/tuff.html` equals the Node transform's.
- `test/room.test.js`, `test/nav.test.js`, `test/app.test.js` — ported to the new protocol: live
  clicks, ranked finishes, `round:end`, updates vs full state, board join, player cap.
- `test/verify.test.js` — fake API: a valid path, a redirect hop, a missing link, a 429.
- `scripts/load-test.js` — opens 100 Socket.IO clients against a local server, clicks 10 times a
  second for a minute, and prints bytes sent per second and the largest message. Target: under
  100 KB/s and no full state during play.
- `tunnel/config.yml.example` and `npm run tunnel`; credentials stay in `~/.cloudflared/`.
- `.env.example` — fix the name: it says `WIKIRUN_CONTACT`, but `server/config.js` reads
  `WIKIROUTES_CONTACT`.

Removed: nothing server-side; `sanitize-html` and `cheerio` stay for the picker's page checks.
Added dependencies: `dompurify` (vendored for the browser), `jsdom` (dev).

## Protocol changes

Client → server, acknowledged as today:
- `nav:go {clicked, landed}` — replaces `nav:go {title}`. Reply `{ok, moves, won}`.
- `nav:back`, `nav:forward` — unchanged names; reply carries the title to show, no HTML.
- `round:end` — host ends the round early.
- `room:watch {code}` — join as the board, no player row.

Server → clients:
- `room:state` — full state, to one socket on join or resume, to everyone on a phase change.
  Players `{id, name, connected, score, moves, finished, rank, bot}`.
- `room:update` — batched small changes: `[{op: 'join' | 'leave' | 'move' | 'finish' | 'verify',
  …}]`, at most two a second.
- `round:start {start, target, endsAt}` — titles only; each player fetches the start page itself.

## Phases

### Phase 0: Spike (half a day)
- [ ] `brew install cloudflared`, then a quick tunnel to wikirun as it is today. Three phones on
      mobile data join a party and play a round. Verify: Socket.IO upgrades to WebSocket through
      the tunnel (DevTools shows `transport=websocket`), and resume works after airplane mode.
- [ ] Named tunnel on `race.<domain>` (see "Try it"). Verify the same from the phones.
- [ ] Rate-limit probe: a throwaway page on the tunnel fetches 30 Wikipedia articles in 60 seconds
      from one phone with `Api-User-Agent` set. Note any 429 and its `Retry-After`, and decide
      whether the client needs a minimum gap between fetches.

### Phase 1: Pages in the browser (one day)
- [ ] `public/article.js` and the jsdom parity test on the Tuff fixture.
- [ ] `public/wiki.js` with a fake `fetch` in tests: parameters, header, cache, 429 wait.
- [ ] `nav:go {clicked, landed}`, `nav.js` entries with `via`, room stops fetching; tests ported.
- [ ] Client renders its own pages; `round:start` carries titles only. Headless browser check at
      320, 390 and 1280 px, as in PLAN.md Phase 3.

### Phase 2: A room of 100 (one day)
- [ ] Batched `room:update`; full `room:state` only on join, resume and phase change.
- [ ] Ranked finishes, `round:end`, points, `MAX_PLAYERS`.
- [ ] HUD, results and standings for 100 players; board view.
- [ ] Cache headers and vendored Socket.IO client. Verify through the tunnel with
      `curl -sI https://race.<domain>/app.js?v=…` twice: `cf-cache-status: HIT` the second time.
- [ ] `scripts/load-test.js`: under 100 KB/s at 10 clicks a second, largest message during play
      under 2 KB.

### Phase 3: Verification (half a day)
- [ ] `server/verify.js` and its tests; the tick or "unverified" on results and the board.
- [ ] Against real Wikipedia: Banana → Augustus → Napoleon passes; a path with a link that is not
      on the page fails.

### Phase 4: Jev bot (half a day, in AIC-HandsOn)
- [ ] `bot.py` with `python-socketio`: joins with `bot: true`, waits for `round:start`, runs the
      existing race loop with `choose_link` from `decide.py` (unchanged), sends
      `nav:go {clicked, landed}` per hop. Verify: Jev's row fills in on the board with a badge and
      a tick, and swapping in an attendee's edited `decide.py` changes the bot's clicks.

### Phase 5: Rehearsal (an hour)
- [ ] Five people on phones over mobile data, the Mac on the connection it will use on the day,
      the board on a second screen, Jev joining after the humans finish. Note 429s, reconnects,
      the Mac's upload rate, and seconds per click.

## Session day

1. Mac plugged in. `caffeinate -dims &`, then `npm start` and `npm run tunnel` in two terminals.
2. Open `https://race.<domain>`, create the party, open `?room=CODE&view=board` on the projector.
   Players scan the QR code and enter their name and email.
3. Host sets the round: 5 minutes, a pair tested in rehearsal. Humans race.
4. Results on the board. Start `bot.py` for the same pair; Jev's row fills in within seconds.
5. Fallbacks: The Wiki Game's private group for the human round; the AIC-HandsOn solo app for Jev.

## Risks

- **The Mac is a single point of failure.** Rooms are in memory; a crash or lost connection ends
  the party. Mitigations above; the fallback is The Wiki Game.
- **Upload from the Mac.** Measured targets keep play under 100 KB/s, but a hotspot on a crowded
  cell can still stall. Rehearse on the connection you will use.
- **Tunnels and WebSockets.** Cloudflare supports WebSockets on all plans and closes idle ones;
  Socket.IO pings every 25 seconds. Cloudflare may restart edge servers and drop sockets; wikirun's
  resume covers it. The tunnel docs do not say WebSockets explicitly, so Phase 0 proves it.
- **Wikipedia rate limits in the browser.** Wikimedia does not document which tier a browser with
  `Api-User-Agent` gets, or whether carrier NAT puts many phones on one budget. The Phase 0 probe
  answers the first; the client's visible wait handles both.
- **Two article transforms.** Node (cheerio) for the picker and browser (DOMParser) for players
  could drift; the parity test on the fixture guards it.
- **Verification from one IP.** About 200 requests after a round, through the server's 150/minute
  limiter, so the last ticks can take a minute or two to appear.

## Try it

One-time tunnel setup (commands from Cloudflare's "Create a locally-managed tunnel" guide):

```sh
brew install cloudflared
cloudflared tunnel login                         # pick your domain in the browser
cloudflared tunnel create wikiroutes             # writes ~/.cloudflared/<UUID>.json
cloudflared tunnel route dns wikiroutes race.<domain>
```

`~/.cloudflared/config.yml`:

```yaml
url: http://localhost:3000
tunnel: <UUID>
credentials-file: /Users/<you>/.cloudflared/<UUID>.json
```

Every time:

```sh
npm install
npm start                       # HOST=127.0.0.1, PUBLIC_URL=https://race.<domain> in .env
cloudflared tunnel run wikiroutes
npm test
```

For a throwaway test without the domain: `cloudflared tunnel --url http://localhost:3000`.
