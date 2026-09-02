#!/usr/bin/env python3
"""Check index.json against the rules this repository states in its README.

The rules are not invented here. Every check below traces to a line in
README.md ("Contributing" and "House rules") or to PluginIndexEntry in
hermes_cli/plugin_index.py upstream. Where the README is stricter than
upstream -- it requires a 40-character commit SHA where upstream would accept
a tag -- the README wins, because a tag can be moved after review and the
whole point of the pin is that what was reviewed is what installs.

Findings are sorted into four buckets, and the difference between them
matters more than the count:

  BLOCKING       a stated rule is broken by something this PR changed
  NEEDS A HUMAN  a rule that cannot be settled from CI -- said plainly rather
                 than guessed at, because a guard that pretends to check
                 something it cannot is worse than no guard
  ADVISORY       recommended, not required; never fails the run
  PRE-EXISTING   already in the index and untouched by this PR; reported so
                 it is visible, never charged to the contributor

Exit 0 clean, 1 blocking findings, 2 the checker itself could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"

# README: "name", "repo", "ref" are the minimum fields.
REQUIRED = ("name", "repo", "ref")

# README: recommended fields.
RECOMMENDED = ("description", "author", "homepage", "tags", "capabilities")

# PluginIndexEntry, upstream. A key outside this set is silently dropped by
# the client, so a typo in a field name does nothing at all and looks fine.
KNOWN = {
    "name", "description", "author", "tags", "repo", "ref",
    "subdir", "homepage", "capabilities", "api_version", "added_at",
}

LIST_OF_STR = ("tags", "capabilities")

SHA = re.compile(r"\A[0-9a-f]{40}\Z")
REPO = re.compile(r"\A[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\Z")
# The bare name a user types after `hermes plugins install`. No separators,
# no spaces -- those would collide with the owner/repo/subdir install forms.
NAME = re.compile(r"\A[a-z0-9][a-z0-9._-]*\Z")


class Findings:
    def __init__(self) -> None:
        self.blocking: list[tuple[str, str, str]] = []
        self.human: list[tuple[str, str, str]] = []
        self.advisory: list[tuple[str, str, str]] = []
        self.existing: list[tuple[str, str, str]] = []

    def block(self, who, what, fix): self.blocking.append((who, what, fix))
    def ask(self, who, what, fix): self.human.append((who, what, fix))
    def advise(self, who, what, fix): self.advisory.append((who, what, fix))
    def old(self, who, what, fix): self.existing.append((who, what, fix))


def gh(path: str) -> tuple[int, dict | None]:
    """One GitHub API read. Returns (status, body-or-None)."""
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "hermes-plugin-index-gate",
    })
    token = (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def load(path_or_text: str, *, is_text: bool = False) -> tuple[dict, str]:
    text = path_or_text if is_text else open(path_or_text, encoding="utf-8").read()
    return json.loads(text), text


def entries_of(doc: dict) -> list[dict]:
    plugins = doc.get("plugins")
    return plugins if isinstance(plugins, list) else []


def shape_checks(entry: dict, f: Findings, report) -> None:
    """Everything determinable from the entry itself, no network."""
    who = entry.get("name") or "(entry with no name)"

    for field in REQUIRED:
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            report(who, f"`{field}` is missing or empty",
                   f"Add `{field}`. The README lists it as a minimum field.")

    ref = entry.get("ref")
    if isinstance(ref, str) and ref.strip() and not SHA.match(ref.strip()):
        report(who, f"`ref` is `{ref}`, which is not a 40-character commit SHA",
               "Replace it with the full commit SHA. A branch or tag can be "
               "moved after review; a commit cannot, so the pin is what makes "
               "'what was reviewed is what installs' true.")

    repo = entry.get("repo")
    if isinstance(repo, str) and repo.strip() and not REPO.match(repo.strip()):
        report(who, f"`repo` is `{repo}`, which is not `owner/name`",
               "Use the bare `owner/name` form -- no URL, no trailing path.")

    name = entry.get("name")
    if isinstance(name, str) and name.strip() and not NAME.match(name.strip()):
        report(who, f"`name` is `{name}`, which is not a plain bare name",
               "Use lowercase letters, digits, dot, dash or underscore. This "
               "is what a user types after `hermes plugins install`, so a "
               "slash or a space collides with the owner/repo/subdir forms.")

    for field in LIST_OF_STR:
        value = entry.get(field)
        if value is not None and (not isinstance(value, list)
                                  or not all(isinstance(x, str) for x in value)):
            report(who, f"`{field}` is not a list of strings",
                   f"Make `{field}` a JSON array of strings.")

    api_version = entry.get("api_version")
    if api_version is not None and not isinstance(api_version, int):
        report(who, f"`api_version` is `{api_version!r}`, not a number",
               "Use an integer, e.g. `1`.")

    unknown = sorted(set(entry) - KNOWN)
    if unknown:
        # Worth flagging loudly: the client drops these, so a misspelled field
        # name has no effect at all and nothing anywhere says so.
        report(who, "unrecognised field(s): " + ", ".join(f"`{u}`" for u in unknown),
               "The client ignores keys outside the schema, so these do "
               "nothing. Check for a typo, or drop them.")


def network_checks(entry: dict, f: Findings) -> None:
    who = entry.get("name") or "(entry with no name)"
    repo = (entry.get("repo") or "").strip()
    ref = (entry.get("ref") or "").strip()
    if not REPO.match(repo):
        return

    # Assert success rather than enumerate the failures we happened to think
    # of. A nonexistent commit answers 422, not 404 -- checking only for 404
    # let a bogus pin through silently, which is the one thing here that must
    # never pass quietly. Status 0 is the instrument failing, not the entry.
    status, body = gh(f"/repos/{repo}")
    if status == 0:
        f.ask(who, f"could not reach the API to check `{repo}`",
              "Network failure during the run, not a finding about the entry. "
              "Re-run before drawing a conclusion.")
        return
    if status != 200:
        f.block(who, f"`{repo}` did not resolve (HTTP {status})",
                "Confirm the repository exists, is public, and is spelled "
                "`owner/name`. The README allows removing entries whose repo "
                "disappears or goes private.")
        return
    if body and body.get("private"):
        f.block(who, f"`{repo}` is private",
                "Users cannot install from a private repository.")
    if body and body.get("archived"):
        f.advise(who, f"`{repo}` is archived",
                 "Still installable, but worth knowing it is unmaintained.")

    if SHA.match(ref):
        status, _ = gh(f"/repos/{repo}/commits/{ref}")
        if status == 0:
            f.ask(who, "could not reach the API to check `ref`",
                  "Network failure during the run. Re-run before concluding.")
        elif status != 200:
            f.block(who, f"`ref` {ref[:12]}\u2026 does not resolve on `{repo}` "
                         f"(HTTP {status})",
                    "The pin points at no commit, so the entry installs "
                    "nothing. Ask for the SHA of the commit to publish.")

    subdir = entry.get("subdir")
    if isinstance(subdir, str) and subdir.strip() and SHA.match(ref):
        status, _ = gh(f"/repos/{repo}/contents/{subdir.strip('/')}?ref={ref}")
        if status == 0:
            f.ask(who, "could not reach the API to check `subdir`",
                  "Network failure during the run. Re-run before concluding.")
        elif status != 200:
            f.block(who, f"`subdir` `{subdir}` does not resolve at that commit "
                         f"(HTTP {status})",
                    "Check the path, or drop `subdir` if the plugin is at the "
                    "repository root.")


def house_rules(added, modified, removed, pr_author: str | None, f: Findings) -> None:
    """The README's House rules, and honesty about the one CI cannot settle."""
    touched = len(added) + len(modified) + len(removed)
    if touched > 1:
        names = sorted(e.get("name", "?") for e in added + modified + removed)
        f.block("this PR", f"changes {touched} entries: {', '.join(names)}",
                "House rules ask for one plugin per PR. Ask for it split.")

    if not pr_author:
        return

    for entry in added:
        owner = (entry.get("repo") or "").split("/")[0]
        who = entry.get("name") or "(entry with no name)"
        if owner and owner.lower() != pr_author.lower():
            # Deliberately not a block. The author may legitimately be a
            # member of an owning org, and org membership is frequently
            # private -- so CI cannot tell "not theirs" from "cannot see".
            f.ask(who, f"listed by `{pr_author}` but the repo is owned by `{owner}`",
                  "House rules ask people to list a plugin they own or "
                  "maintain. This may be fine if they maintain it under that "
                  "org. Worth one question before merging.")

    for entry in modified:
        who = entry.get("name") or "(entry with no name)"
        owner = (entry.get("repo") or "").split("/")[0]
        if owner and owner.lower() != pr_author.lower():
            f.ask(who, f"edited by `{pr_author}`, who does not own `{owner}`",
                  "House rules say only the listing author edits their own "
                  "entry. Confirm before merging.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="index.json")
    ap.add_argument("--base-ref", help="git ref to diff against, e.g. origin/main")
    ap.add_argument("--pr-author")
    ap.add_argument("--summary", help="file to append a markdown readout to")
    args = ap.parse_args()

    f = Findings()

    try:
        doc, text = load(args.file)
    except FileNotFoundError:
        print(f"{args.file} not found", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        f.block(args.file, f"is not valid JSON: {e}",
                "Fix the syntax. Nothing else can be checked until it parses.")
        emit(f, args.summary, checked=0)
        return 1

    if not isinstance(doc, dict) or not isinstance(doc.get("plugins"), list):
        f.block(args.file, "has no top-level `plugins` array",
                "The client reads `{\"plugins\": [ ... ]}`.")
        emit(f, args.summary, checked=0)
        return 1

    entries = entries_of(doc)

    # Guards the guard: an index that parsed to nothing is not a clean run.
    if not entries:
        print("index.json parsed but contains no entries", file=sys.stderr)
        return 2

    canonical = json.dumps(doc, indent=2) + "\n"
    if text != canonical:
        f.advise(args.file, "is not formatted as 2-space JSON",
                 "Re-serialise with 2-space indent so diffs stay reviewable. "
                 "Advisory only -- the README does not require it.")

    seen: dict[str, int] = {}
    for entry in entries:
        name = entry.get("name")
        if isinstance(name, str):
            seen[name] = seen.get(name, 0) + 1
    for name, count in seen.items():
        if count > 1:
            f.block(name, f"appears {count} times in the index",
                    "Bare-name resolution needs one entry per name.")

    # Which entries this PR is actually responsible for.
    added, modified, removed = [], [], []
    base_entries: dict[str, dict] = {}
    if args.base_ref:
        try:
            raw = subprocess.run(["git", "show", f"{args.base_ref}:{args.file}"],
                                 capture_output=True, text=True, check=True).stdout
            base_doc, _ = load(raw, is_text=True)
            base_entries = {e.get("name"): e for e in entries_of(base_doc)
                            if isinstance(e.get("name"), str)}
        except Exception:
            base_entries = {}

        now = {e.get("name"): e for e in entries if isinstance(e.get("name"), str)}
        for name, entry in now.items():
            if name not in base_entries:
                added.append(entry)
            elif entry != base_entries[name]:
                modified.append(entry)
        removed = [e for name, e in base_entries.items() if name not in now]

    touched_names = {e.get("name") for e in added + modified}
    gating = bool(args.base_ref)

    for entry in entries:
        name = entry.get("name")
        is_touched = (not gating) or (name in touched_names)
        # A rule broken by an entry nobody touched is real, and is still not
        # the contributor's to fix. Reported, never charged to them.
        shape_checks(entry, f, f.block if is_touched else f.old)
        if is_touched:
            for field in RECOMMENDED:
                if not entry.get(field):
                    f.advise(name or "(entry with no name)",
                             f"has no `{field}`",
                             "Recommended, not required.")
            network_checks(entry, f)

    house_rules(added, modified, removed, args.pr_author, f)

    emit(f, args.summary, checked=len(touched_names) if gating else len(entries))
    return 1 if f.blocking else 0


def emit(f: Findings, summary_path: str | None, *, checked: int) -> None:
    out: list[str] = []
    w = out.append

    if f.blocking:
        w("## Blocking — ask for these before merging\n")
        for who, what, fix in f.blocking:
            w(f"- **{who}** — {what}\n  - {fix}")
        w("")
    if f.human:
        w("## Needs your eyes — CI cannot settle these\n")
        for who, what, fix in f.human:
            w(f"- **{who}** — {what}\n  - {fix}")
        w("")
    if f.advisory:
        w("## Advisory — fine to merge without\n")
        for who, what, fix in f.advisory:
            w(f"- **{who}** — {what}\n  - {fix}")
        w("")
    if f.existing:
        w("## Already in the index — not this PR's doing\n")
        for who, what, fix in f.existing:
            w(f"- **{who}** — {what}\n  - {fix}")
        w("")
    if not (f.blocking or f.human or f.advisory or f.existing):
        w(f"Clean. {checked} entr{'y' if checked == 1 else 'ies'} checked "
          "against the README's rules, nothing to ask for.")

    body = "\n".join(out)
    print(body)
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("# Plugin index review\n\n" + body + "\n")


if __name__ == "__main__":
    sys.exit(main())
