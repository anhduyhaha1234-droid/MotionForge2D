# Skill installation report — 2026-10-01

Installed **13 new skills, 155 files** under `C:/Users/Admin/.codex/skills/`. Verified all **445 pre-existing skill files unchanged**. Existing **10 Spec Kit skills retained**; the project was not initialized or regenerated. The refreshed Codex skill catalog now lists the new skills.

This is a selected skills installation, not ten fully activated plugin frameworks. No upstream setup/runtime scripts, model calls, hook registration, global configuration edits, AGENTS replacements, telemetry, or Hermes launch/install occurred. The bundled official skill installer supplied path/name validation, safe ZIP extraction, skill validation, and complete directory copying. Source commits, exact installed paths, and SHA-256 of every installed file are in [SKILLS_INSTALL_MANIFEST.json](SKILLS_INSTALL_MANIFEST.json).

## Status of the ten requested repositories

| Repository | Actual result |
|---|---|
| obra/superpowers | **Not installed.** Codex plugin policy returned `DISABLED_BY_ADMIN / NOT_AVAILABLE` as recorded by the parent reviewer. No file-copy workaround was used. |
| EveryInc/compound-engineering-plugin | Installed `ce-debug`, `ce-code-review`, `ce-compound`, `ce-plan` with all files in their skill directories. Recovered selected directories from the complete cached ZIP, avoiding an unrelated Windows path-length failure in upstream test fixtures. |
| github/spec-kit | Retained 10 existing skills unchanged; new upstream source cached. Did not claim the retained skills are regenerated from the latest commit. No `specify init`. |
| bmad-code-org/BMAD-METHOD | Source cached only. `_bmad` project runtime and module setup are not installed. |
| garrytan/gstack | Source cached only. Host generation, runtime sidecar, Bash/Bun/Node/browser setup are not installed or tested. |
| OthmanAdi/planning-with-files | Installed Codex skill and its 25 support files. Removed executable `hooks:` frontmatter from the new local SKILL.md; manual use only. Upstream and local hashes are both recorded. |
| affaan-m/ECC | Installed `search-first`, `cost-aware-llm-pipeline`, `eval-harness`. No full ECC plugin, config sync, MCP, autonomous loops, or runtime enforcement. |
| wshobson/agents | Installed `python-background-jobs`, `python-testing-patterns`, `e2e-testing-patterns`, including references. No agent marketplace or model-tier defaults activated. |
| VoltAgent/awesome-claude-code-subagents | Agent role references cached only; repository has no SKILL.md at the pinned snapshot. No role was misreported as an installed skill. |
| beltonk/claude-code-agent-skills | Installed `handing-off-sessions`, `compacting-context` with their support files. No project instruction template was applied. |

## Installed inventory

Each path below starts with `C:/Users/Admin/.codex/skills/` and ends in `/SKILL.md`.

| Skill directory | Files | Installed SKILL.md SHA-256 |
|---|---:|---|
| ce-debug | 9 | `82540da83cbe42ff462a75557752b5f4313e5fe0fa89d5bb047c29eec6de5a80` |
| ce-code-review | 40 | `4dbdc4485af006035e1a8622735e58eb4298be69b404b1241e748b0057a7e9ac` |
| ce-compound | 28 | `951669e685c804a16138736c4bf132ee5f6ed9bbee3e3ccd5cbb096dd253b5d6` |
| ce-plan | 36 | `6c5842bfc91a9aad65fcdf83669f86ef499a9b40dc99f9340c5981d2bc6f1720` |
| planning-with-files | 26 | `f88d6e61a6d2378bd124931a15f7e9b30019516c496f7fd7105cf837da18e184` |
| search-first | 1 | `76835db48dd910061d2e4271b1151793d2fddbabeb2d2866eed068b3580c55d5` |
| cost-aware-llm-pipeline | 1 | `2d6c19c2d21a473db8720c4f723f17d265eeec48f84614f0169be2df2fbe28ff` |
| eval-harness | 2 | `49a5a10975860bb2d7e3c4e260ff19b6580e43f5fbc7770b32dece02dde48e49` |
| python-background-jobs | 2 | `ea99e3f1d4df0e0c7260e3d6436003ea980c55d8b1ad6950ba63048491eb531e` |
| python-testing-patterns | 3 | `a1020718f31629c2a5b20731cad1804dbb81b18800495c5cebdf16e6cac9c175` |
| e2e-testing-patterns | 2 | `1653690dde9eeca6dcb66086277791c2a3ccc2b37eaab6ec9b627a10adfb94be` |
| handing-off-sessions | 2 | `e54052f8da1a151d84b7d0482501e1f4f9a96bf92d5db222caa44992c5656ea9` |
| compacting-context | 3 | `d280d3e534948e567b53b78498e91cbacd6bce7672cda11839b2b492db600ea0` |

## Application to MotionForge

For the next media prototype, read `search-first`, `cost-aware-llm-pipeline`, and the relevant existing acceptance/evidence skill. Use one short plan and a bounded attempt ledger. Do not invoke every newly installed framework. `ce-plan` and Spec Kit remain available for the later integration task; they are not prerequisites to render a prototype.

Use `ce-code-review` in a scoped local path when code review is actually needed. Its upstream full mode includes cross-model routes and additional agents; installed availability is not authorization to launch those for this project. Existing user limits, no external model dispatch, ownership, and Codex review authority override conflicting workflow defaults. Optional CE routes to other uninstalled skills are not represented as available.

Use cost examples as patterns only: upstream model names/pricing/caching syntax must be checked against the actual configured provider. A copied budget example does not establish hard request enforcement. The handoff/compaction skills preserve useful state; private reasoning and excessive transcript rereads are not required. Scripts are available as files but were not executed or certified for this environment.

Hermes can read these exact local skill paths when the user hands over the next prompt. No file was copied to `.hermes`, and no Hermes process was started. The user's current demo-first request remains the task priority.

## Evidence

- [Machine manifest](SKILLS_INSTALL_MANIFEST.json): all 13 skills, all 155 file hashes, all ten repository statuses, pinned commits, source and installed hashes.
- [Before snapshot](SKILLS_BEFORE.json): prior directory list and 445 prior file hashes.
- [Installation script](install_selected_skills.py): local cached-source installation using official helper functions; refuses existing destinations and unsafe archive paths.
- [Compatibility review](SKILL_COMPATIBILITY_REVIEW.md): official sources and runtime distinctions.

The installation script is intentionally one-shot: rerunning it now must refuse to overwrite the installed skill directories.
