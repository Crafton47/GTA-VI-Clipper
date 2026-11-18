"""Faceless Clipping Page Operating System (`page_os.py`).

Implements the complete automation workflow from the Faceless GTA 6 Clipping Page Setup Prompt:
- Section 4 & 7: 7 Content Pillars + Platform-Specific Copy Templates (X no-hashtags + credit last,
  Instagram 3-5 hashtags max + value lines, TikTok/Shorts punchy hook + credit).
- Section 5 & 14: Creator Credit (`🎥 @creator`), Takedown Blocklist (`takedowns.md`),
  Leak/Datamine/Exploit Rejection, and Launch-Week Spoiler Tagging (`SPOILER`).
- Section 6: Tight 7-30s trim mode (`--tight`), first-second Hook Bar (max 1 emoji), and value/context note.
- Section 9 & 10: Daily 6-Slot Content Generator (`--daily-pack`) with live Reddit question/trend discovery
  and automatic GTA 6 Launch Countdown / Post-Launch Day Counter (Nov 19, 2026).
- Section 13 & 15: Workspace folder & file structure (`playbook.md`, `facts.md`, `idea-bank.md`,
  `watchlist.md`, `log.md`, `scoreboard.csv`, `learning.md`, `takedowns.md`, `media/{official,raw,edits}`)
  plus automated `--review` learning loop analyzer.
"""

import csv
import datetime
import json
import re
import shutil
import urllib.request
from pathlib import Path

from . import config, moments
from .util import log, slugify

LAUNCH_DATE = datetime.date(2026, 11, 19)

SCOREBOARD_COLUMNS = [
    "post_id", "date", "time", "platform", "pillar", "format", "hook",
    "length_sec", "credit", "views_12h", "views_24h", "views_72h",
    "likes", "reposts_or_shares", "replies_or_comments",
    "saves_or_bookmarks", "followers_at_read", "test_name", "notes",
]

PLAYBOOK_TEMPLATE = """# Faceless GTA 6 Clipping & Fan Page Playbook

- **Page Name**: {page_name} (`@{handle}`)
- **Platforms**: X, Instagram Reels, TikTok, YouTube Shorts, Threads
- **Time Zone**: {tz}
- **Niche Angle**: Fast official news, HOW TO utility tips, credited streamer/gameplay clips, and GTA nostalgia.
- **Disclosure (Every Bio)**: "GTA 6 news, tips and the best clips, fast. Fan page, not affiliated with Rockstar Games."

## Daily 6-Slot Schedule (X + Vertical Video Platforms)
1. **Morning (09:00)**: Official news recap (`official_news`)
2. **Mid-Morning (11:30)**: HOW TO utility tip (`tips_and_tutorials`)
3. **Midday (14:00)**: Edited 9:16 gameplay/streamer clip #1 (`gameplay_clips` -> X, Reels, TikTok, Shorts)
4. **Afternoon (16:30)**: GTA 5 nostalgia one-liner or community question (`nostalgia` / `questions`)
5. **Early Evening (19:00)**: Character/car/map spotlight or 9:16 gameplay clip #2 (`spotlights` / `gameplay_clips`)
6. **Night (21:30)**: Launch countdown / "Day X in Leonida" daily recap (`countdown_recap`)

## Hard Rules (Safety, Credit & Quality)
1. **Credit Every Clip**: Always include `🎥 @creator` (or `🎥 @RockstarGames` for official footage) on its own line.
2. **Zero Leaks or Exploits**: Never post leaks, datamined files, leaked builds, pirated copies, or "play early" tricks.
3. **Transform Every Clip**: Tight 7-30s trim (cut dead air, end on payoff), rounded top Hook Bar (1 emoji max), centered pop captions, and value commentary in caption.
4. **No Spoilers in Hook**: Never put story spoilers in the top Hook Bar or thumbnail; mark story clips with `SPOILER:` in the caption.
5. **Instant Takedowns**: Any creator listed in `takedowns.md` is automatically skipped by the clipper.
"""

FACTS_TEMPLATE = """# Verified GTA 6 Official Facts (`facts.md`)

Every fact used in news recaps, HOW TO posts, or captions must trace to an official source below:

- **Official Release Date**: November 19, 2026 on PlayStation 5 and Xbox Series X|S (Source: https://www.rockstargames.com/VI).
- **Setting**: State of Leonida, featuring Vice City and surrounding regions including Grassrivers, Leonida Keys, Mount Kalaga, Port Gellhorn, and Ambrosia (Source: https://www.rockstargames.com/VI).
- **Protagonists**: Lucia Caminos and Jason Duval (Source: https://www.rockstargames.com/VI).
- **Unlock Timing**: PlayStation Store regional midnight local time unlock means New Zealand (NZDT) and Australia (AEDT) unlock first before Europe and the Americas (Source: PlayStation Store regional release schedule).
"""

WATCHLIST_TEMPLATE = """# Monitored Official Sources, Streamers & Subreddits (`watchlist.md`)

## 1. Official Sources (Check First - Safest to Use)
- Rockstar Games GTA 6 Portal & Media: https://www.rockstargames.com/VI
- Rockstar Newswire: https://www.rockstargames.com/newswire
- Official Accounts: `@RockstarGames` (X, Instagram, YouTube, TikTok), `@PlayStation`, `@Xbox`

## 2. Priority Streamers & Creators (Synced with `streamers.txt`)
- `youtube:@IShowSpeed` (IShowSpeed)
- `twitch:kaicenat` (Kai Cenat)
- `twitch:xqc` (xQc)
- `twitch:timthetatman` (TimTheTatman)
- `twitch:caseoh_` (CaseOh)
- `twitch:jynxzi` (Jynxzi)
- `twitch:summit1g` (summit1g)
- `twitch:lirik` (LIRIK)
- `twitch:ludwig` (Ludwig)

## 3. Community Discovery Subreddits
- https://www.reddit.com/r/GTA6/hot.json
- https://www.reddit.com/r/GrandTheftAutoV/hot.json
"""

IDEA_BANK_TEMPLATE = """# Ready-to-Post Drafts by Content Pillar (`idea-bank.md`)

## Pillar 1: Official News Recap (`official_news`)
1. **Leonida Map Regions Breakdown**:
   GTA 6 Leonida regions confirmed by Rockstar:

   - Vice City: neon urban core and Ocean Beach
   - Leonida Keys: tropical archipelago in the south
   - Grassrivers: untamed wetlands and airboats
   - Mount Kalaga: northern hunting and off-road trails

   🎥 @RockstarGames

2. **Console Launch Specs**:
   GTA 6 launches on PS5 and Xbox Series X|S:

   - Unlocks midnight local time per region
   - New Zealand and Australia enter Leonida first
   - Clear at least 150 GB of SSD space before preload

   🎥 @RockstarGames

## Pillar 2: HOW TO Tips (`tips_and_tutorials`)
3. **HOW TO PREP YOUR PS5 OR XBOX FOR GTA 6 LAUNCH NIGHT**:
   1. Enable Auto-Download in system power settings (Rest Mode on PS5 / Sleep on Xbox)
   2. Free up 150+ GB on your internal NVMe SSD
   3. Verify your account region and payment method before midnight local unlock

   Zero waiting when the clock hits 00:00.

4. **HOW TO SPOT FAKE GTA 6 LEAKS vs OFFICIAL FOOTAGE**:
   1. Check rockstargames.com/VI or @RockstarGames first
   2. Look for AI artifacting on HUD icons and street signs
   3. Ignore "early access code" scams - review builds have strict watermark locks

   Save your account from copyright strikes and scams.

5. **HOW TO EXPLORE LEONIDA FAST ON DAY 1**:
   1. Unlock a fast sports bike or helicopter before heading to the Keys
   2. Pin gas stations and safe houses along the Port Gellhorn highway
   3. Turn on high-contrast radar in Display settings for night chases

   You will cover 3x more of the map in your first session.

## Pillar 3: GTA 5 Nostalgia (`nostalgia`)
6. 13 years of Los Santos. Tomorrow, we leave for Vice City.
7. From Franklin's first repo mission in 2013 to Lucia and Jason in 2026. What a ride.
8. One last sunset drive down Del Perro Freeway before Leonida takes over.

## Pillar 4: Character & Map Spotlights (`spotlights`)
9. **Mount Kalaga National Park**: Northern Leonida's wilderness - kayaking, off-road dirt bikes, and hunting trails far away from Vice City sirens. 🎥 @RockstarGames
10. **Grassrivers**: Swamp airboats, gators, and hidden contraband routes across Leonida's wetlands. 🎥 @RockstarGames
11. **Port Gellhorn**: Motels, pawn shops, and high-speed highway pursuits on Leonida's rugged west coast. 🎥 @RockstarGames

## Pillar 5: Launch Countdowns & Recaps (`countdown_recap`)
12. **Pre-Launch Countdown**:
    {days_to_launch}

    Every trailer frame analyzed, every console prepped. Vice City awaits.

13. **Launch Day 1 Template**:
    Day 1 in Leonida: First look at Vice City traffic density, weather physics, and NPC reactions.

## Pillar 6: High-Reply Community Questions (`questions`)
14. Where are you driving first in GTA 6: Ocean Beach, the Keys bridge, or straight to Mount Kalaga?
15. Who had the best reaction to entering Vice City for the first time today?
"""

LEARNING_TEMPLATE = """# Content Learning Loop (`learning.md`)

## Current Proven Rules (Baseline)
- **Wins**:
  - Official trailer/gameplay clips with a 4-8 word top Hook Bar beat plain reposts.
  - Credited creator reaction clips (`7-30s`, setup -> scream/reaction -> hard cut) pull highest completion rates.
  - `HOW TO` utility posts with 3 numbered steps get the most bookmarks/saves on X and Instagram.
  - Emotional "13 years of Los Santos" nostalgia one-liners drive high like-to-view ratios.
- **Losses to Avoid**:
  - Clips longer than 35s with post-moment chatter lose viewer retention after the climax.
  - Putting hashtags on X posts reduces reach (keep X at 0 hashtags, credit on final line).
  - More than 1 emoji in the top Hook Bar looks spammy; keep it to 1 emoji max (`😭`, `💀`, `🔥`, or `👀`).

## Weekly Review Log
_Run `python scripts/run.py --review` after logging 24h/72h metrics in `scoreboard.csv` to auto-populate top/bottom posts and new rules here._
"""

TAKEDOWNS_TEMPLATE = """# Creator Takedown & Do-Not-Clip List (`takedowns.md`)
# Add one creator name or handle per line below (e.g. `@examplecreator`).
# The clipper automatically checks this file before clipping any video/stream and refuses to clip listed creators.
"""


def init_page_workspace(base_dir=None, page_name="GTA6FastClips", handle="gta6fastclips", tz="IST (UTC+5:30)"):
    """Create the complete Section 15 folder & file hierarchy if missing."""
    root = Path(base_dir) if base_dir else (config.HOME / "page")
    root.mkdir(parents=True, exist_ok=True)
    for sub in ("official", "raw", "edits"):
        (root / "media" / sub).mkdir(parents=True, exist_ok=True)

    today = datetime.date.today()
    delta = (LAUNCH_DATE - today).days
    if delta > 0:
        days_str = f"{delta} days until GTA 6 unlocks."
    elif delta == 0:
        days_str = "0 days. GTA 6 unlocks TONIGHT at midnight local time."
    else:
        days_str = f"Day {abs(delta)} in Leonida."

    files = {
        "playbook.md": PLAYBOOK_TEMPLATE.format(page_name=page_name, handle=handle, tz=tz),
        "facts.md": FACTS_TEMPLATE,
        "watchlist.md": WATCHLIST_TEMPLATE,
        "idea-bank.md": IDEA_BANK_TEMPLATE.format(days_to_launch=days_str),
        "learning.md": LEARNING_TEMPLATE,
        "takedowns.md": TAKEDOWNS_TEMPLATE,
    }
    for fname, content in files.items():
        fpath = root / fname
        if not fpath.exists():
            fpath.write_text(content, encoding="utf-8")

    log_path = root / "log.md"
    if not log_path.exists():
        log_path.write_text("# Published & Generated Content Log (`log.md`)\n\n", encoding="utf-8")

    sb_path = root / "scoreboard.csv"
    if not sb_path.exists():
        with open(sb_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(SCOREBOARD_COLUMNS)

    return root


def is_creator_blocked(creator_name, page_dir=None):
    """Check `takedowns.md` (Section 5 Rule 5) to ensure we never clip a blocked creator."""
    root = Path(page_dir) if page_dir else (config.HOME / "page")
    td = root / "takedowns.md"
    if not td.exists():
        return False
    norm = re.sub(r"[^a-z0-9]", "", (creator_name or "").lower())
    if not norm:
        return False
    for line in td.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.split("#")[0].strip().lstrip("@").lower()
        blocked = re.sub(r"[^a-z0-9]", "", line)
        if blocked and (blocked in norm or norm in blocked):
            return True
    return False


def sanitize_hook_and_safety(moment, stream):
    """Enforce Section 5, 6 & 14 rules on a clip candidate:
    1. Reject leaks, datamines, pirated builds, or 'play early' exploits.
    2. Enforce max 1 emoji in `hook_text` and remove spoilers from `hook_text`.
    3. Format creator credit (`🎥 @handle` or `🎥 @RockstarGames`).
    """
    combined = f"{moment.get('hook_text', '')} {moment.get('caption', '')} {moment.get('reason', '')}".lower()
    forbidden = ("leaked build", "datamined", "pirated copy", "play early glitch", "code exploit", "leaked map")
    if any(bad in combined for bad in forbidden):
        return None

    hook = (moment.get("hook_text") or "").strip()
    emojis_found = [ch for ch in hook if ord(ch) >= 0x1F300 or (0x2600 <= ord(ch) <= 0x27BF)]
    if len(emojis_found) > 1:
        kept_first = False
        cleaned = []
        for ch in hook:
            if ord(ch) >= 0x1F300 or (0x2600 <= ord(ch) <= 0x27BF):
                if not kept_first:
                    cleaned.append(ch)
                    kept_first = True
            else:
                cleaned.append(ch)
        hook = re.sub(r"\s+", " ", "".join(cleaned)).strip()

    spoiler_terms = ("ending", "final mission", "dies", "death of", "betrays", "final boss", "credits roll")
    is_spoiler = bool(moment.get("spoiler")) or any(st in combined for st in spoiler_terms)
    if is_spoiler:
        for st in spoiler_terms:
            hook = re.sub(re.escape(st), "THIS MOMENT", hook, flags=re.I)
        cap = (moment.get("caption") or "").strip()
        if not cap.upper().startswith("SPOILER"):
            moment["caption"] = f"SPOILER: {cap}"

    moment["hook_text"] = hook
    creator_raw = (stream.get("name") or "creator").strip().lstrip("@").replace(" ", "")
    if "rockstar" in creator_raw.lower():
        credit = "🎥 @RockstarGames"
    else:
        credit = f"🎥 @{creator_raw}"
    moment["credit"] = credit
    return moment


def format_platform_captions(clip, stream):
    """Generate exact per-platform copy following Section 7 rules:
    - X: No hashtags. Short headline, blank line, value/reaction line, credit line last.
    - Instagram Reels: Hook line, 1-2 sentences of value, credit line, 3 to 5 hashtags max.
    - TikTok & YouTube Shorts: Short punchy caption + credit + 3-4 hashtags.
    """
    credit = clip.get("credit") or f"🎥 @{stream.get('name', 'creator').replace(' ', '')}"
    hook_line = (clip.get("hook_text") or "Watch this moment").strip()
    cap_line = (clip.get("caption") or "Wait for the payoff at the end.").strip()
    reason_line = (clip.get("reason") or "").strip()

    raw_tags = clip.get("hashtags") or ["#gta6", "#gtavi", "#gaming", "#clips"]
    clean_tags = []
    for t in raw_tags:
        t = t.strip()
        if not t.startswith("#"):
            t = "#" + t
        if t.lower() not in [x.lower() for x in clean_tags]:
            clean_tags.append(t)
    if "#gta6" not in [x.lower() for x in clean_tags] and "gta" in (stream.get("title") or "").lower():
        clean_tags.insert(0, "#gta6")
    ig_tags = " ".join(clean_tags[:5])       # Instagram max 5 hashtags rule
    tt_tags = " ".join(clean_tags[:4])       # TikTok / Shorts 3-4 hashtags

    x_copy = f"{hook_line}\n\n{cap_line}\n\n{credit}"
    ig_copy = f"{hook_line}\n\n{cap_line}" + (f" {reason_line}" if reason_line and reason_line not in cap_line else "") + f"\n\n{credit}\n\n{ig_tags}"
    tt_copy = f"{cap_line} {credit} {tt_tags}"

    return {
        "x_twitter": x_copy,
        "instagram_reels": ig_copy,
        "tiktok_shorts": tt_copy,
        "credit": credit,
    }


def record_clips_to_page_os(outdir, stream, clips, page_dir=None):
    """Sync finished clips into `page/media/edits/`, append to `log.md`, and add rows to `scoreboard.csv`."""
    root = init_page_workspace(page_dir)
    edits_dir = root / "media" / "edits"
    sb_path = root / "scoreboard.csv"
    log_path = root / "log.md"

    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    existing_rows = 0
    if sb_path.exists():
        with open(sb_path, "r", encoding="utf-8", errors="ignore") as fh:
            existing_rows = max(0, sum(1 for _ in fh) - 1)

    log_entries = []
    with open(sb_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for idx, c in enumerate(clips, 1):
            post_id = f"CLIP-{date_str.replace('-', '')}-{existing_rows + idx:03d}"
            src_mp4 = outdir / c["file"]
            dst_name = f"{date_str}_{slugify(stream['name'], 16)}_{c['file']}"
            dst_mp4 = edits_dir / dst_name
            if src_mp4.exists():
                shutil.copy2(src_mp4, dst_mp4)
            c["page_edit_path"] = str(dst_mp4)
            c["post_id"] = post_id
            copy_blocks = format_platform_captions(c, stream)
            c["platform_copy"] = copy_blocks

            writer.writerow([
                post_id, date_str, time_str, "Reels/TikTok/Shorts/X", "gameplay_clips",
                f"9:16_{c.get('layout', 'auto')}", c.get("hook_text", ""),
                round(float(c.get("duration", 0)), 1), copy_blocks["credit"],
                "", "", "", "", "", "", "", "", "hook_and_trim_v1",
                f"score={c.get('score', 0)} src={stream.get('url', '')}",
            ])
            log_entries.append(
                f"### [{post_id}] {date_str} {time_str} - {c.get('hook_text', '')}\n"
                f"- **Media**: `{dst_mp4}` ({c.get('duration', 0):.0f}s, score {c.get('score', 0)})\n"
                f"- **Source**: {stream.get('url', '')} @ {int(c.get('stream_start', 0))}s\n"
                f"- **Credit**: `{copy_blocks['credit']}`\n"
            )

    if log_entries:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(log_entries) + "\n")


def fetch_reddit_trends(subreddit="GTA6", limit=8):
    """Fetch top trending posts/questions from r/GTA6 (public JSON, no API key needed) for Section 5 Discovery."""
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-ViralClipper/3.0"})
    out = []
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for child in (data.get("data") or {}).get("children") or []:
                d = child.get("data") or {}
                if d.get("stickied"):
                    continue
                out.append({
                    "title": d.get("title", ""),
                    "score": d.get("score", 0),
                    "comments": d.get("num_comments", 0),
                    "url": f"https://www.reddit.com{d.get('permalink', '')}",
                })
    except Exception:
        pass
    return out


def generate_daily_pack(cfg, page_dir=None):
    """Generate today's 6-Slot Daily Schedule (`DAILY_QUEUE.md`) across all Section 4 & 7 pillars."""
    root = init_page_workspace(page_dir)
    today = datetime.date.today()
    delta = (LAUNCH_DATE - today).days
    if delta > 0:
        countdown_hook = f"{delta} days."
        countdown_line = "GTA 6 unlocks November 19, 2026 at midnight local time. Early time zones (New Zealand & Australia) play first."
    elif delta == 0:
        countdown_hook = "0 days. TONIGHT."
        countdown_line = "GTA 6 unlocks at midnight local time on PS5 and Xbox Series X|S. Clear your queue - Vice City is live."
    else:
        countdown_hook = f"Day {abs(delta)} in Leonida."
        countdown_line = "Best discoveries, hidden spots, and top streamer reactions from Vice City today."

    trends = fetch_reddit_trends("GTA6", limit=6)
    trend_lines = "\n".join(f"- {t['title']} ({t['score']} upvotes, {t['comments']} comments)" for t in trends[:5])
    if not trend_lines:
        trend_lines = "- Preload size, midnight local unlock regions, and first vehicle choices in Vice City."

    prompt = f"""You manage a high-growth faceless GTA 6 page. Today is {today.isoformat()} ({countdown_hook}).
Verified facts only (Launch: Nov 19, 2026 on PS5 & Xbox Series X|S; Setting: Leonida / Vice City, Leonida Keys, Grassrivers, Mount Kalaga, Port Gellhorn; Protagonists: Lucia & Jason). Never invent leaks or fake rumors.

Current community discussions:
{trend_lines}

Generate a JSON object with keys `slot1_news`, `slot2_howto`, `slot4_nostalgia`, `slot5_spotlight`, `slot6_question` following these exact rules:
- `slot1_news`: Fast official recap (Headline, blank line, 3-4 hyphen bullets of verified facts, ends with `🎥 @RockstarGames`, NO hashtags).
- `slot2_howto`: ALL-CAPS `HOW TO ... IN GTA 6` hook, 3 numbered steps (1, 2, 3), and a 1-line payoff.
- `slot4_nostalgia`: Emotional "13 years of Los Santos" era-ending one-liner + transition to Vice City.
- `slot5_spotlight`: 2-3 punchy lines spotlighting one verified Leonida region, character, or vehicle + `🎥 @RockstarGames`.
- `slot6_question`: Simple, high-reply 1-sentence question every GTA fan can answer in the comments.
Return ONLY valid JSON."""

    ai_slots = {}
    try:
        if moments.resolve_provider(cfg) != "heuristic":
            raw = moments._ask(prompt, cfg)
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                ai_slots = json.loads(m.group(0))
    except Exception as exc:
        log(f"Daily pack AI note ({exc}) -> using verified built-in templates", "warn")

    s1 = ai_slots.get("slot1_news") or (
        "GTA 6 Launch & Preload Checklist (Verified):\n\n"
        "- Releases November 19, 2026 on PS5 and Xbox Series X|S\n"
        "- Unlocks at midnight local time (New Zealand & Australia play first)\n"
        "- Features 6 confirmed Leonida regions from Vice City to Mount Kalaga\n\n"
        "🎥 @RockstarGames"
    )
    s2 = ai_slots.get("slot2_howto") or (
        "HOW TO GET READY FOR GTA 6 UNLOCK NIGHT\n\n"
        "1. Enable Rest Mode / Sleep auto-download on your PS5 or Xbox Series X|S\n"
        "2. Clear 150+ GB on your internal SSD so preload never stalls\n"
        "3. Avoid story spoilers on launch morning by muting leaked keyword tags\n\n"
        "You will be driving down Ocean Beach the second the clock hits 00:00."
    )
    s4 = ai_slots.get("slot4_nostalgia") or (
        "13 years of Los Santos.\n\n"
        "From PS3 midnight lines in 2013 to Leonida on PS5 & Series X. We made it."
    )
    s5 = ai_slots.get("slot5_spotlight") or (
        "Leonida Spotlight: Grassrivers 🐊\n\n"
        "Airboats, mangrove swamps, and off-grid hideouts right outside Vice City. "
        "Where will you test the water physics first?\n\n🎥 @RockstarGames"
    )
    s6 = ai_slots.get("slot6_question") or "What is the very first thing you are doing the second you gain control in GTA 6?"

    queue_md = f"""# Daily 6-Slot Content Queue - {today.isoformat()}

_Auto-generated for X, Instagram Reels, TikTok, YouTube Shorts & Threads (`page_os.py`)._

## Slot 1 (Morning - 09:00): Official News Recap (`X / Threads`)
```text
{s1}
```

## Slot 2 (Mid-Morning - 11:30): HOW TO Utility Tip (`X / Instagram Carousel / Threads`)
```text
{s2}
```

## Slot 3 (Midday - 14:00): Gameplay / Streamer Clip #1 (`Reels / TikTok / Shorts / X`)
- Upload the top-scoring `.mp4` from `page/media/edits/` and paste the platform-matched caption from `POST.md`.

## Slot 4 (Afternoon - 16:30): GTA 5 Nostalgia One-Liner (`X / Threads`)
```text
{s4}
```

## Slot 5 (Early Evening - 19:00): Spotlight or Clip #2 (`X / Reels / TikTok / Shorts`)
```text
{s5}
```

## Slot 6 (Night - 21:30): Countdown / Daily Recap + Community Question (`X / Threads`)
```text
{countdown_hook}

{countdown_line}

{s6}
```
"""
    out_file = root / f"DAILY_QUEUE_{today.isoformat()}.md"
    out_file.write_text(queue_md, encoding="utf-8")
    (root / "DAILY_QUEUE_LATEST.md").write_text(queue_md, encoding="utf-8")
    log(f"generated 6-slot daily content pack: {out_file}", "ok")
    return out_file


def review_scoreboard(page_dir=None):
    """Section 13 Learning Loop: Analyze `scoreboard.csv` and append data-backed insights to `learning.md`."""
    root = init_page_workspace(page_dir)
    sb_path = root / "scoreboard.csv"
    learn_path = root / "learning.md"
    rows = []
    with open(sb_path, "r", encoding="utf-8", errors="ignore") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            rows.append(r)

    scored = []
    for r in rows:
        v = r.get("views_72h") or r.get("views_24h") or r.get("views_12h") or ""
        try:
            views = float(v)
        except ValueError:
            views = -1.0
        scored.append((views, r))

    with_views = [item for item in scored if item[0] >= 0]
    today_str = datetime.date.today().isoformat()
    report = [f"\n### Automated Review - {today_str}", f"- **Total Logged Clips/Posts**: {len(rows)}"]
    if with_views:
        with_views.sort(key=lambda x: -x[0])
        vals = [x[0] for x in with_views]
        median_v = vals[len(vals) // 2]
        top = with_views[0][1]
        bot = with_views[-1][1]
        report.append(f"- **Median Views**: {median_v:,.0f}")
        report.append(f"- **Top Performer**: `{top.get('post_id')}` ({with_views[0][0]:,.0f} views) - Hook: *{top.get('hook')}* ({top.get('length_sec')}s)")
        report.append(f"- **Lowest Performer**: `{bot.get('post_id')}` ({with_views[-1][0]:,.0f} views) - Hook: *{bot.get('hook')}* ({bot.get('length_sec')}s)")
    else:
        report.append("- **Note**: Fill `views_12h`, `views_24h`, or `views_72h` in `scoreboard.csv` to compute top/bottom performers.")

    with open(learn_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(report) + "\n")
    log(f"updated learning loop in {learn_path}", "ok")
    return "\n".join(report)
