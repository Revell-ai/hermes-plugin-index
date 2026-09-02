# hermes-plugin-index

Community plugin index for [Hermes Agent](https://github.com/NousResearch/hermes-agent).

`hermes plugins install <bare-name>` resolves names through this index. `hermes plugins search <term>` searches it. The list here is what `hermes_cli/plugin_index.py` reads.

## Pointing your client here

Bare-name resolution reads whichever index the client is configured with. To use
this one, add to `~/.hermes/config.yaml`:

```yaml
plugins:
  index_url: https://raw.githubusercontent.com/Revell-ai/hermes-plugin-index/main/index.json
```

Full identifiers need no configuration:

```console
$ hermes plugins install Revell-ai/revell-onyx
```

### Known limitation: model-provider entries

Entries with `kind: model-provider` are discoverable through this index but do
not currently install correctly — by bare name or by full identifier. The
install reports success and the security scan passes, but Hermes places the
plugin under `~/.hermes/plugins/` while the provider registry only discovers
providers under `~/.hermes/plugins/model-providers/`. The provider never loads.

`hermes plugins enable` does not rescue it. Enable also reports success, and
the provider still does not load — which is where the debugging time tends to
go.

The directory it lands in is not necessarily the name you typed. The installer
takes `manifest["name"]` when it can read a manifest, falls back to the
`subdir` basename, and falls back again to the repository name
([plugins_cmd.py#L800](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/plugins_cmd.py#L800)).
An `owner/repo` install of a plugin whose manifest lives in a subdirectory
therefore finds no manifest at the root and installs the whole repository under
its repo name. The `owner/repo/subdir` form resolves to the same directory as
the bare name and is the better one to publish:

```console
$ hermes plugins install Revell-ai/revell-onyx/lark
```

This is a client-side path mismatch, not an index problem. Tracked at
[NousResearch/hermes-agent#76372](https://github.com/NousResearch/hermes-agent/issues/76372),
with a fix open at
[NousResearch/hermes-agent#76387](https://github.com/NousResearch/hermes-agent/pull/76387).

## Contributing

Open a PR that adds an entry to `index.json`. Minimum fields:

- `name` — the bare name users type after `hermes plugins install`
- `repo` — `owner/repo` on GitHub
- `ref` — **a full 40-character commit SHA.** Not a branch, not a tag
- `subdir` — optional path inside the repo, for monorepos hosting multiple plugins

Recommended fields: `description`, `author`, `homepage`, `tags`, `capabilities`.

`ref` is a full SHA because a branch or tag can be moved after review. A commit
cannot. What was reviewed is what installs.

### House rules

- **List a plugin you own or maintain.** Not someone else's repo.
- **One plugin per PR.**
- **Only the listing author edits their own entry.**
- Entries may be removed if the repo disappears, goes private, or is reported
  malicious.

### Automated check

A check runs on pull requests that touch `index.json` and writes what it found
to the run summary. It separates what blocks a merge from what only needs a
look — a missing recommended field will not fail the run.

Two things worth knowing before it surprises you. It cannot tell whether you
maintain a repository you do not own, because org membership is usually
private, so where that applies it asks a maintainer rather than guessing
either way. And anything it finds in entries your PR did not touch is reported
separately and is not yours to fix.

### Reporting a plugin problem

Open it on that plugin's own repo, not here. This index carries metadata; it
does not host the code and cannot fix it.

The schema is defined by `PluginIndexEntry` in [hermes_cli/plugin_index.py](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/plugin_index.py).

**Indexed ≠ audited.** Inclusion here is a metadata review only, not a code audit. Review a plugin before enabling it.

## Hosting

This repository is hosted under the [Revell-ai](https://github.com/Revell-ai) org as ecosystem infrastructure. Ownership can transfer to [NousResearch](https://github.com/NousResearch) whenever they'd like it under their org — see [NousResearch/hermes-agent#87565](https://github.com/NousResearch/hermes-agent/issues/87565) for the conversation.

## License

MIT — see [LICENSE](LICENSE).
