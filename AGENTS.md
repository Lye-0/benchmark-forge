# Development rules

- Follow docs/IMPLEMENTATION_BRIEF.md and docs/WINDOWS_IMPLEMENTATION_BRIEF.md (Windows-native additions); record incomplete and unverified features honestly.
- Generate problems using deterministic algorithms only. Never call a model to generate them.
- Keep grading answers out of model inputs. Freeze and persist complete sets before evaluation.
- Default to localhost. Never execute submitted code or agent commands on the host.
- GPU, external accounts and paid APIs are optional. Fail closed if isolation is not verified.
- AI answer diagnostics use only a fresh Codex Cloud sub-agent given public problem text,
  with no inherited history or reference answers; keep reports outside production results.
- For newly spawned sub-agents, use gpt-6-astra with medium reasoning as requested by the user.
- Preserve credentials, model weights and local results outside Git. Do not choose a code license.
- Use existing isolated checkouts; do not create worktrees unless the user requests one.
- Run backend tests/lint/types and web tests/types/build before reporting completion.
- If creating commits, use Japanese Conventional Commits. No external deployment.

- Continue across phase boundaries without waiting for confirmation. Stop only for a necessary user decision/action, after completing independent work.
- When stopping, report the reached stage as N/7 (Phase 0–6), distinguish it from completed phases, and state the outstanding condition and required user action.
