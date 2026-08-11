# Code Review Remediation Plan

**Goal:** Resolve every verified finding from the full-project review without weakening deterministic test coverage.

**Security design:** Pull requests run only unprivileged validation and tests. Production Azure OIDC and secrets remain available only to the trusted deployment workflow. The Web App identity receives `Key Vault Secrets User` separately on the five runtime secrets it consumes, never on the vault itself. Third-party Actions are pinned to immutable release commits and checkout credentials are not persisted.

**Runtime design:** Proof-verification JSON is accepted only when its fields have the exact safe types and confidence is finite and in range. `/add_habit --verify` rejects unknown or malformed policies. Weekday patterns require at least seven completions spanning fourteen days. Mem0 returns at most twenty insights through its supported `top_k` argument.

**Delivery design:** Keep replayed provider integration tests in CI because their VCR cassettes are committed. Add regression tests first, implement each fix, then run unit tests, integration tests, Ruff, formatting, Pyrefly, shell/config validation, and OpenTofu formatting/validation where credentials are not required.

## Tasks

1. Add failing runtime and configuration regression tests.
2. Harden proof parsing and command parsing.
3. Add pattern evidence thresholds and bounded memory retrieval.
4. Remove privileged pull-request planning and correct the native Groq model configuration.
5. Pin Actions, disable persisted checkout credentials, and include `scripts/startup.sh` in deployment filtering.
6. Replace vault-wide Web App access with per-secret role assignments.
7. Run the final container as a dedicated non-root user.
8. Run focused and full verification suites.
