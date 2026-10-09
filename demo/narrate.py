"""Narrated demo: plays the whole story by itself and explains every step, for videos.

    python demo/narrate.py                 # one run, about 4 minutes
    python demo/narrate.py --pace 7        # slower captions
    python demo/narrate.py --loop          # repeat forever (resets between runs)

Open the pages with &narrate=1 to show the captions on screen:

    http://127.0.0.1:5173/blast-radius?api=http://127.0.0.1:8100&narrate=1
    http://127.0.0.1:5173/dashboard?api=http://127.0.0.1:8100&narrate=1

Unlike driver.py, nobody needs to click. This script plays the human reviewer too: it dismisses
Gemma's medium findings (a reviewer disagreeing with the AI) and approves held edits. Every
caption says what is happening, where in the system it happens, and why.

Captions are printed here and written to web/public/narration.json (gitignored), which the
frontend's overlay polls. Needs the engine on :8100 with Ollama running.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import edits as script  # noqa: E402
from driver import AGENT, DEFAULT_URL, MODEL, Engine  # noqa: E402

CAPTION_FILE = Path(__file__).resolve().parent.parent / "web" / "public" / "narration.json"
AFTER_PROMOTION = 2

CHECK_NAMES = {
    "hardcode_hunter": "Hardcode Hunter",
    "reality_check": "Reality Check",
    "scope_guard": "Scope Guard",
    "test_guardian": "Test Guardian",
    "impact_analyst": "Impact Analyst",
}

BOLD, DIM, GREEN, AMBER, RED, CYAN, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[0m"
TONE_COLOUR = {"info": CYAN, "good": GREEN, "warn": AMBER, "bad": RED}


class Narrator:
    def __init__(self, pace: float) -> None:
        self.pace = pace
        self.step = 0

    def caption(self, title: str, body: str, where: str, tone: str = "info", hold: float = 1.0) -> None:
        """Show one caption, then wait `pace * hold` seconds so a viewer can read it."""
        self.step += 1
        colour = TONE_COLOUR[tone]
        print(f"\n{colour}{BOLD}▌ {title}{RESET}")
        print(f"  {body}")
        print(f"  {DIM}where: {where}{RESET}", flush=True)
        CAPTION_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CAPTION_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "step": self.step, "title": title, "body": body, "where": where, "tone": tone,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }))
        tmp.replace(CAPTION_FILE)  # atomic, so the overlay never reads half a file
        time.sleep(self.pace * hold)

    def clear(self) -> None:
        CAPTION_FILE.unlink(missing_ok=True)


def findings_for(engine: Engine, finding_ids: list[str]) -> list[dict]:
    wanted = set(finding_ids)
    return [f for f in engine.state()["findings"] if f["id"] in wanted]


def describe(finding: dict) -> str:
    who = "Gemma 4" if finding["source"] == "gemma" else "a pattern check"
    return (f"{CHECK_NAMES[finding['check']]} ({who}, {finding['severity']}) at "
            f"{finding['file']}:{finding['line']}: {finding['message']}")


def submit(engine: Engine, edit: script.ScriptedEdit) -> dict:
    return engine.call("POST", "/edits", {
        "agent": AGENT, "model": MODEL, "prompt": edit.prompt, "file": edit.file,
        "before": edit.before, "after": edit.after,
    })


def score(engine: Engine) -> tuple[int, str]:
    agent = engine.agent()
    return (agent["score"], agent["tier"]) if agent else (500, "probation")


def review_held(n: Narrator, engine: Engine, result: dict, number: int) -> None:
    """Play the human reviewer for a held edit: dismiss Gemma's medium findings, then approve."""
    found = findings_for(engine, result["finding_ids"])
    disputed = [f for f in found if f["source"] == "gemma" and f["severity"] != "high"]
    serious = [f for f in found if f not in disputed]
    if serious:  # never in the scripted clean edits; don't approve something risky on camera
        n.caption("Leaving this one held",
                  "There's a serious finding, so the reviewer doesn't approve it: " + describe(serious[0]),
                  "Findings panel", "warn")
        engine.call("POST", "/decisions", {"edit_id": result["edit_id"], "decision": "deny"})
        return
    for finding in disputed:
        n.caption("Gemma raised a concern",
                  describe(finding) + ". It's cautious, and only medium severity. Gemma can flag things, "
                  "but it can never approve or block on its own.",
                  "Findings panel ← Gemma 4 on the local GPU (Ollama)", "warn", hold=1.4)
        engine.call("POST", f"/findings/{finding['id']}/verdict", {"verdict": "dismiss"})
        n.caption("The reviewer dismisses it",
                  "A person disagrees with the AI here. Dismissing it is recorded as a false alarm, which "
                  "earns the agent +2 and is stored in the event log.",
                  "Findings panel → POST /findings/{id}/verdict → event log", "info")
    before, _ = score(engine)
    engine.call("POST", "/decisions", {"edit_id": result["edit_id"], "decision": "approve"})
    after, tier = score(engine)
    n.caption(f"Edit {number} approved: {before} → {after}",
              f"A clean, approved edit earns up to +14, scaled by how much the edit changes, so tiny edits "
              f"can't farm trust. The agent is at {after}, {tier}.",
              "Held-edit dialog → POST /decisions → score rebuilt from the log → dashboard card", "good")


def run(n: Narrator, engine: Engine) -> None:
    engine.call("POST", "/admin/reset")
    n.caption("viz_trust: autonomy is earned, not assumed",
              "An AI coding agent is about to edit a small Python app. Every edit goes through viz_trust "
              "first: checks, a decision, and a trust score that decides how much a human must review.",
              "Everything runs on this laptop: engine :8100, Gemma 4 via Ollama, this page", "info", hold=1.6)
    n.caption("The agent starts on probation",
              "A new agent has no history, so it starts at 500 out of 1000. On probation, every edit is "
              "held until a human approves it.",
              "Engine → scoring rules (engine/scoring.py)", "info", hold=1.2)

    clean = script.clean_edits()
    number = 0
    promoted_at = None
    for edit in clean:
        number += 1
        if promoted_at is not None and number > promoted_at + AFTER_PROMOTION:
            break
        _, tier = score(engine)
        n.caption(f"Edit {number}: \"{edit.prompt}\"",
                  f"The agent changes {edit.file}. Before anything is saved, the engine runs pattern checks, "
                  f"then Gemma 4's judgement checks, then works out which functions the edit touches and who "
                  f"calls them.",
                  "POST /edits → engine/checks/patterns.py + gemma_checks.py + graph.py", "info",
                  hold=1.0 if number > 2 else 1.4)
        result = submit(engine, edit)
        found = findings_for(engine, result["finding_ids"])
        if number == 1:
            n.caption("The graph lights up",
                      "The edited function glows, and its callers ripple outward: these are the places this "
                      "edit could break. The colour is the trust tier of the agent that made the change.",
                      "Blast radius page ← engine/graph.py (Python ast)", "info", hold=1.4)
        if result["decision"] == "hold":
            why = "the agent is on probation" if tier == "probation" else "a check found something serious"
            n.caption(f"Held for review: {why}",
                      f"{len(found)} finding(s). The edit is waiting, not saved. A human decides.",
                      "Held-edit dialog (Blast radius page)", "warn")
            review_held(n, engine, result, number)
        else:
            extra = f" with {len(found)} low-priority finding(s) left for later" if found else ""
            n.caption(f"Edit {number} went straight through{extra}",
                      f"The agent is {tier}: clean edits no longer need approval, which is the point of "
                      f"earning trust. The graph still shows what changed.",
                      "Engine decision: allow", "good")
        new_score, new_tier = score(engine)
        if promoted_at is None and new_tier == "standard":
            promoted_at = number
            n.caption(f"Promoted to Standard at {new_score}",
                      f"{number} clean edits earned it. From now on, clean edits go straight through, and only "
                      f"edits with a high-severity finding are held.",
                      "Dashboard card: tier pill, 'Why this score'", "good", hold=1.6)

    if promoted_at is None:
        n.caption("The agent didn't reach Standard",
                  "The scripted edits ran out first. Reset and run again.", "demo/narrate.py", "bad")
        return

    slack = script.slack_edit()
    before, tier = score(engine)
    n.caption(f"Now the risky edit: \"{slack.prompt}\"",
              f"The agent is trusted enough to work alone ({before}, {tier}). This time it hardcodes a Slack "
              f"token and imports a package called slack_notify_pro.",
              "POST /edits", "warn", hold=1.4)
    result = submit(engine, slack)
    found = findings_for(engine, result["finding_ids"])
    for finding in found:
        n.caption("Caught: " + CHECK_NAMES[finding["check"]], describe(finding),
                  "Findings panel ← " + ("Gemma 4, checked against PyPI" if finding["source"] == "gemma"
                                         else "pattern check (no AI needed)"), "bad", hold=1.3)
    after, tier = score(engine)
    n.caption(f"Denied, never written to disk. {before} → {after}, {tier}",
              "A secret is denied at any tier. The agent drops straight back to probation, so every edit it "
              "makes is held again. One mistake costs more than a run of good edits earned.",
              "Engine decision: deny → event log → dashboard card", "bad", hold=1.8)
    n.caption("All of it ran locally",
              "Gemma 4 E4B on a 6 GB laptop GPU, about 2 seconds per edit. No API key, and no code left "
              "the machine. Every step is in an append-only log, so the score can always be explained.",
              "viz_trust", "info", hold=2.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Play the demo by itself with captions, for videos.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--pace", type=float, default=5.0, help="seconds per caption (default 5)")
    parser.add_argument("--loop", action="store_true", help="repeat forever, resetting between runs")
    args = parser.parse_args()

    engine = Engine(args.url)
    narrator = Narrator(args.pace)
    try:
        engine.call("GET", "/health")
    except OSError:
        sys.exit(f"The engine isn't answering at {args.url}. Start it with: uvicorn engine.app:app --port 8100")
    try:
        while True:
            run(narrator, engine)
            if not args.loop:
                break
            narrator.caption("Starting again", "Resetting the event log for the next run.", "demo/narrate.py",
                             "info", hold=1.0)
    except KeyboardInterrupt:
        pass
    finally:
        narrator.clear()


if __name__ == "__main__":
    main()
