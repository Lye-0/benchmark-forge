# Development rules

- Follow docs/IMPLEMENTATION_BRIEF.md; record incomplete and unverified features honestly.
- Generate problems using deterministic algorithms only. Never call a model to generate them.
- Keep grading answers out of model inputs. Freeze and persist complete sets before evaluation.
- Default to localhost. Never execute submitted code or agent commands on the host.
- GPU, external accounts and paid APIs are optional. Fail closed if isolation is not verified.
- AI answer diagnostics use only a fresh Codex Cloud sub-agent given public problem text,
  with no inherited history or reference answers; keep reports outside production results.
- Preserve credentials, model weights and local results outside Git. Do not choose a code license.
- Use existing isolated checkouts; do not create worktrees unless the user requests one.
- Run backend tests/lint/types and web tests/types/build before reporting completion.
- If creating commits, use Japanese Conventional Commits. No external deployment.
