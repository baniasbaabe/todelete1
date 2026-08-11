# Hardening & Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the AI Habit Tracker for production: configurable infra, centralized logging, retry resilience, least-privilege DB access, and race-free persistence.

**Architecture:** Five sequential change areas. Steps 1-2 are infra-only (Terraform/Terragrunt). Step 3 is app-only (Python). Steps 4-5 bridge both. Each step produces a working system and its own commit.

**Tech Stack:** OpenTofu/Terragrunt (Azure), Python 3.13, tenacity, asyncpg, SQLAlchemy, Alembic, structlog

## Global Constraints

- Python 3.13, modern union syntax (`X | None` not `Optional[X]`)
- `uv` package manager, NOT pip
- Ruff linter/formatter with existing config in pyproject.toml
- Tests use pytest + pytest-asyncio with `asyncio_mode = "auto"`
- VCR (vcrpy) for HTTP cassettes, testcontainers for Postgres integration tests
- All Terraform variables marked `sensitive = true` where they carry secrets
- Terragrunt root config at `infra/root.hcl`, live configs at `infra/live/*/terragrunt.hcl`
- Azure provider `~> 4.0`, random provider `~> 3.6`
- structlog for all Python logging — JSON to stdout
- The actual `teardown` script is `scripts/destroy.sh` (not teardown.sh)

---

### Task 1: Resource Group Variable Extraction

**Files:**
- Modify: `infra/root.hcl:7`
- Modify: `infra/root.hcl:28`
- Modify: `scripts/bootstrap.sh:27`
- Modify: `scripts/deploy.sh:90,157`
- Modify: `scripts/post-deploy.sh:20`
- Modify: `scripts/bootstrap-db-roles.sh` (no hardcoded RG — already uses terragrunt output, OK)
- Modify: `scripts/destroy.sh:138,172,207`

**Interfaces:**
- Consumes: nothing
- Produces: `AZURE_RESOURCE_GROUP` env var convention used by all scripts and `root.hcl`

- [ ] **Step 1: Update `infra/root.hcl`**

Replace the hardcoded resource group in `locals` and `remote_state`:

```hcl
locals {
  # Azure configuration
  location       = "swedencentral"
  resource_group = get_env("AZURE_RESOURCE_GROUP")
  environment    = "live"

  # ... rest unchanged
}
```

In the `remote_state` block, replace the hardcoded value:

```hcl
  config = {
    resource_group_name  = local.resource_group
    storage_account_name = get_env("TFSTATE_STORAGE_ACCOUNT")
    container_name       = get_env("TFSTATE_CONTAINER", "tofu-state")
    key                  = "${path_relative_to_include()}/tofu.tfstate"
  }
```

- [ ] **Step 2: Update `scripts/bootstrap.sh`**

At the top of the script, after the color definitions and before the config file path, replace:

```bash
RESOURCE_GROUP="<resource-group>"
```

with:

```bash
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:?AZURE_RESOURCE_GROUP is required}"
```

- [ ] **Step 3: Update `scripts/deploy.sh`**

Find this line in the state config loading section:

```bash
        if az storage account show --name "$TFSTATE_STORAGE_ACCOUNT" --resource-group "${TFSTATE_RESOURCE_GROUP:-$AZURE_RESOURCE_GROUP}" &> /dev/null; then
```

Replace with:

```bash
        if az storage account show --name "$TFSTATE_STORAGE_ACCOUNT" --resource-group "${TFSTATE_RESOURCE_GROUP:-$AZURE_RESOURCE_GROUP}" &> /dev/null; then
```

Find the line:

```bash
export TF_VAR_tfstate_resource_group="${TFSTATE_RESOURCE_GROUP:-$AZURE_RESOURCE_GROUP}"
```

Replace with:

```bash
export TF_VAR_tfstate_resource_group="${TFSTATE_RESOURCE_GROUP:-$AZURE_RESOURCE_GROUP}"
```

- [ ] **Step 4: Update `scripts/post-deploy.sh`**

Replace:

```bash
RESOURCE_GROUP="<resource-group>"
```

with:

```bash
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:?AZURE_RESOURCE_GROUP is required}"
```

- [ ] **Step 5: Update `scripts/destroy.sh`**

Add at the top, after the color definitions:

```bash
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:?AZURE_RESOURCE_GROUP is required}"
```

Then replace all literal test resource-group occurrences with `$RESOURCE_GROUP`, including:
- Line 138: use `--resource-group "${TFSTATE_RESOURCE_GROUP:-$RESOURCE_GROUP}"`
- Line 172: use `echo "Resource group '$RESOURCE_GROUP' still exists."`
- Commented-out section lines 197-207: update the resource group references to `$RESOURCE_GROUP`

- [ ] **Step 6: Verify no remaining hardcoded references**

Run a literal search for the retired test resource-group name across `infra/` and `scripts/`.

Expected: no matches outside of comments/documentation.

- [ ] **Step 7: Commit**

```bash
git add infra/root.hcl scripts/bootstrap.sh scripts/deploy.sh scripts/post-deploy.sh scripts/destroy.sh
git commit -m "feat(infra): extract resource group to AZURE_RESOURCE_GROUP env var

Readers change one variable instead of hunting across files.
Requires each operator to select a resource group explicitly."
```

---

### Task 2: Shared Log Analytics Workspace & Diagnostic Settings

**Files:**
- Create: `infra/modules/log-analytics/main.tf`
- Create: `infra/modules/log-analytics/variables.tf`
- Create: `infra/modules/log-analytics/outputs.tf`
- Create: `infra/live/log-analytics/terragrunt.hcl`
- Modify: `infra/modules/phoenix/main.tf`
- Modify: `infra/modules/phoenix/variables.tf`
- Modify: `infra/modules/phoenix/outputs.tf`
- Modify: `infra/live/phoenix/terragrunt.hcl`
- Modify: `infra/modules/postgres/main.tf`
- Modify: `infra/modules/postgres/variables.tf`
- Modify: `infra/live/postgres/terragrunt.hcl`
- Modify: `infra/modules/keyvault/main.tf`
- Modify: `infra/modules/keyvault/variables.tf`
- Modify: `infra/live/keyvault/terragrunt.hcl`
- Modify: `infra/modules/web-app/main.tf`
- Modify: `infra/modules/web-app/variables.tf`
- Modify: `infra/live/web-app/terragrunt.hcl`
- Modify: `scripts/deploy.sh`
- Modify: `scripts/destroy.sh`

**Interfaces:**
- Consumes: Task 1's `AZURE_RESOURCE_GROUP` convention
- Produces: `workspace_id` output consumed by phoenix, postgres, keyvault, web-app modules

- [ ] **Step 1: Create the log-analytics module**

Create `infra/modules/log-analytics/main.tf`:

```hcl
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.name_prefix}-logs-${random_string.suffix.result}"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = var.tags
}
```

Create `infra/modules/log-analytics/variables.tf`:

```hcl
variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "location" {
  description = "Azure region for resources"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
```

Create `infra/modules/log-analytics/outputs.tf`:

```hcl
output "workspace_id" {
  description = "ID of the Log Analytics Workspace"
  value       = azurerm_log_analytics_workspace.main.id
}

output "workspace_name" {
  description = "Name of the Log Analytics Workspace"
  value       = azurerm_log_analytics_workspace.main.name
}
```

- [ ] **Step 2: Create the live Terragrunt config**

Create `infra/live/log-analytics/terragrunt.hcl`:

```hcl
include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../modules/log-analytics"
}
```

- [ ] **Step 3: Consolidate Phoenix — remove its own workspace**

In `infra/modules/phoenix/main.tf`, remove the entire `azurerm_log_analytics_workspace` resource block:

```hcl
# DELETE this entire resource:
resource "azurerm_log_analytics_workspace" "phoenix" {
  ...
}
```

Change the Container App Environment to use the shared workspace ID:

```hcl
resource "azurerm_container_app_environment" "phoenix" {
  name                = "${var.name_prefix}-phoenix-env-${random_string.phoenix_suffix.result}"
  location            = var.location
  resource_group_name = var.resource_group_name

  log_analytics_workspace_id = var.log_analytics_workspace_id

  tags = var.tags
}
```

In `infra/modules/phoenix/variables.tf`, add:

```hcl
variable "log_analytics_workspace_id" {
  description = "ID of the shared Log Analytics Workspace"
  type        = string
}
```

In `infra/modules/phoenix/outputs.tf`, remove `log_analytics_workspace_id` output and update its description comment. Replace:

```hcl
output "log_analytics_workspace_id" {
  description = "ID of the Log Analytics Workspace"
  value       = azurerm_log_analytics_workspace.phoenix.id
}
```

with nothing (delete the output).

In `infra/live/phoenix/terragrunt.hcl`, add the log-analytics dependency:

```hcl
dependency "log_analytics" {
  config_path = "../log-analytics"
}
```

And add to the `inputs` block:

```hcl
  log_analytics_workspace_id = dependency.log_analytics.outputs.workspace_id
```

- [ ] **Step 4: Add diagnostic settings to postgres module**

In `infra/modules/postgres/variables.tf`, add:

```hcl
variable "log_analytics_workspace_id" {
  description = "ID of the shared Log Analytics Workspace for diagnostic settings"
  type        = string
}
```

In `infra/modules/postgres/main.tf`, add at the end:

```hcl
resource "azurerm_monitor_diagnostic_setting" "postgres" {
  name                       = "${var.name_prefix}-pg-diag"
  target_resource_id         = azurerm_postgresql_flexible_server.main.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "PostgreSQLLogs"
  }

  enabled_log {
    category = "PostgreSQLFlexSessions"
  }

  metric {
    category = "AllMetrics"
    enabled  = false
  }
}
```

In `infra/live/postgres/terragrunt.hcl`, add:

```hcl
dependency "log_analytics" {
  config_path = "../log-analytics"
}
```

And add to `inputs`:

```hcl
  log_analytics_workspace_id = dependency.log_analytics.outputs.workspace_id
```

- [ ] **Step 5: Add diagnostic settings to keyvault module**

In `infra/modules/keyvault/variables.tf`, add:

```hcl
variable "log_analytics_workspace_id" {
  description = "ID of the shared Log Analytics Workspace for diagnostic settings"
  type        = string
}
```

In `infra/modules/keyvault/main.tf`, add at the end:

```hcl
resource "azurerm_monitor_diagnostic_setting" "keyvault" {
  name                       = "${var.name_prefix}-kv-diag"
  target_resource_id         = azurerm_key_vault.main.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "AuditEvent"
  }

  metric {
    category = "AllMetrics"
    enabled  = false
  }
}
```

In `infra/live/keyvault/terragrunt.hcl`, add:

```hcl
dependency "log_analytics" {
  config_path = "../log-analytics"
}
```

And add to `inputs`:

```hcl
  log_analytics_workspace_id = dependency.log_analytics.outputs.workspace_id
```

- [ ] **Step 6: Add diagnostic settings to web-app module**

In `infra/modules/web-app/variables.tf`, add:

```hcl
variable "log_analytics_workspace_id" {
  description = "ID of the shared Log Analytics Workspace for diagnostic settings"
  type        = string
}
```

In `infra/modules/web-app/main.tf`, add at the end:

```hcl
resource "azurerm_monitor_diagnostic_setting" "webapp" {
  name                       = "${var.name_prefix}-webapp-diag"
  target_resource_id         = azurerm_linux_web_app.main.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "AppServiceConsoleLogs"
  }

  enabled_log {
    category = "AppServiceHTTPLogs"
  }

  enabled_log {
    category = "AppServicePlatformLogs"
  }

  metric {
    category = "AllMetrics"
    enabled  = false
  }
}
```

In `infra/live/web-app/terragrunt.hcl`, add:

```hcl
dependency "log_analytics" {
  config_path = "../log-analytics"
}
```

And add to `inputs`:

```hcl
  log_analytics_workspace_id = dependency.log_analytics.outputs.workspace_id
```

- [ ] **Step 7: Update deploy.sh — add log-analytics phase**

After Phase 1 (ACR) and before Phase 2 (Key Vault), insert:

```bash
echo ""
echo "========================================="
echo "Phase 1.5: Deploying Log Analytics Workspace"
echo "========================================="
cd log-analytics
terragrunt init
terragrunt apply -auto-approve
cd ..

echo ""
echo -e "${GREEN}✓ Log Analytics Workspace deployed successfully${NC}"
```

- [ ] **Step 8: Update destroy.sh — add log-analytics teardown**

After Phase 5 (ACR destroy) and before Phase 6 (storage account), insert:

```bash
echo ""
echo "Phase 5.5: Destroying Log Analytics..."
cd log-analytics && terragrunt destroy -auto-approve && cd ..
```

- [ ] **Step 9: Commit**

```bash
git add infra/modules/log-analytics/ infra/live/log-analytics/ \
  infra/modules/phoenix/ infra/live/phoenix/terragrunt.hcl \
  infra/modules/postgres/main.tf infra/modules/postgres/variables.tf \
  infra/live/postgres/terragrunt.hcl \
  infra/modules/keyvault/main.tf infra/modules/keyvault/variables.tf \
  infra/live/keyvault/terragrunt.hcl \
  infra/modules/web-app/main.tf infra/modules/web-app/variables.tf \
  infra/live/web-app/terragrunt.hcl \
  scripts/deploy.sh scripts/destroy.sh
git commit -m "feat(infra): centralized Log Analytics with diagnostic settings

One workspace for all resources. Phoenix's standalone workspace is
consolidated. Diagnostic settings ship App Service console/HTTP/platform
logs, PostgreSQL query logs and sessions, and Key Vault audit events."
```

---

### Task 3: Tenacity Retry Logic

**Files:**
- Create: `src/habit_tracker/infrastructure/resilience.py`
- Create: `tests/unit/test_resilience.py`
- Modify: `pyproject.toml:7` (add tenacity dependency)
- Modify: `src/habit_tracker/infrastructure/ai/llm_client.py`
- Modify: `src/habit_tracker/infrastructure/memory/mem0_store.py`

**Interfaces:**
- Consumes: nothing
- Produces: `retry_llm()` and `retry_store()` decorator factories used by llm_client and mem0_store

- [ ] **Step 1: Add tenacity to pyproject.toml**

In the `dependencies` list, add `"tenacity"` after `"certifi"`:

```toml
dependencies = [
    "python-telegram-bot[webhooks]",
    "sqlalchemy[asyncio]",
    "asyncpg",
    "litellm",
    "mem0ai",
    "arize-phoenix-otel",
    "openinference-instrumentation-litellm",
    "structlog",
    "alembic",
    "psycopg2-binary",
    "python-dotenv",
    "greenlet",
    "certifi",
    "tenacity",
]
```

Run: `uv sync`

- [ ] **Step 2: Write failing tests for the resilience module**

Create `tests/unit/test_resilience.py`:

```python
from __future__ import annotations

import pytest

from habit_tracker.infrastructure.resilience import retry_llm, retry_store


class TestRetryLlm:
    async def test_succeeds_on_first_attempt(self) -> None:
        call_count = 0

        @retry_llm()
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_rate_limit(self) -> None:
        import litellm

        call_count = 0

        @retry_llm()
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise litellm.RateLimitError(
                    message="rate limited", model="test", llm_provider="test"
                )
            return "recovered"

        result = await flaky()
        assert result == "recovered"
        assert call_count == 3

    async def test_does_not_retry_auth_error(self) -> None:
        import litellm

        @retry_llm()
        async def bad_auth():
            raise litellm.AuthenticationError(
                message="bad key", model="test", llm_provider="test"
            )

        with pytest.raises(litellm.AuthenticationError):
            await bad_auth()

    async def test_exhausts_retries(self) -> None:
        import litellm

        @retry_llm()
        async def always_fail():
            raise litellm.RateLimitError(
                message="rate limited", model="test", llm_provider="test"
            )

        with pytest.raises(litellm.RateLimitError):
            await always_fail()


class TestRetryStore:
    async def test_succeeds_on_first_attempt(self) -> None:
        call_count = 0

        @retry_store()
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_connection_error(self) -> None:
        call_count = 0

        @retry_store()
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("connection reset")
            return "recovered"

        result = await flaky()
        assert result == "recovered"
        assert call_count == 2

    async def test_exhausts_retries(self) -> None:
        @retry_store()
        async def always_fail():
            raise ConnectionError("connection reset")

        with pytest.raises(ConnectionError):
            await always_fail()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_resilience.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'habit_tracker.infrastructure.resilience'`

- [ ] **Step 4: Implement the resilience module**

Create `src/habit_tracker/infrastructure/resilience.py`:

```python
from __future__ import annotations

import logging

import structlog
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

_logger = structlog.get_logger()
_stdlib_logger = logging.getLogger("habit_tracker.resilience")


def retry_llm():
    """Retry decorator for LLM API calls.

    3 attempts, 1-10s exponential backoff with jitter.
    Retries transient failures only; auth and content errors propagate immediately.
    """
    import litellm

    return retry(
        retry=retry_if_exception_type((
            litellm.RateLimitError,
            litellm.APIConnectionError,
            litellm.Timeout,
            litellm.ServiceUnavailableError,
        )),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        before_sleep=before_sleep_log(_stdlib_logger, logging.WARNING),
        reraise=True,
    )


def retry_store():
    """Retry decorator for data store calls (mem0, persistence).

    2 attempts, 0.5-4s exponential backoff with jitter.
    Shorter budget because stores are non-critical — fall back quickly.
    """
    return retry(
        retry=retry_if_exception_type((
            ConnectionError,
            OSError,
            TimeoutError,
        )),
        stop=stop_after_attempt(2),
        wait=wait_exponential_jitter(initial=0.5, max=4),
        before_sleep=before_sleep_log(_stdlib_logger, logging.WARNING),
        reraise=True,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_resilience.py -v`

Expected: all PASS

- [ ] **Step 6: Apply `@retry_llm()` to LiteLLMClient**

In `src/habit_tracker/infrastructure/ai/llm_client.py`, add import and decorate:

```python
from __future__ import annotations

import json
from typing import Protocol

from habit_tracker.infrastructure.resilience import retry_llm


class LLMClient(Protocol):
    # ... unchanged ...


class LiteLLMClient:
    def __init__(self, model: str, temperature: float) -> None:
        self._model = model
        self._temperature = temperature

    @retry_llm()
    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Plain text completion."""
        import litellm

        response = await litellm.acompletion(
            model=model or self._model,
            messages=messages,
            temperature=temperature if temperature is not None else self._temperature,
        )
        return response.choices[0].message.content

    @retry_llm()
    async def complete_json(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
    ) -> dict:
        """JSON completion — returns parsed dict."""
        import litellm

        response = await litellm.acompletion(
            model=model or self._model,
            messages=messages,
            temperature=temperature if temperature is not None else self._temperature,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
```

- [ ] **Step 7: Apply `@retry_store()` to Mem0MemoryStore**

In `src/habit_tracker/infrastructure/memory/mem0_store.py`, add import and decorate the inner operations:

```python
"""Mem0-backed implementation of the MemoryStore protocol."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

from habit_tracker.application.dtos.memory_dto import MemoryInsight
from habit_tracker.infrastructure.resilience import retry_store

logger = structlog.get_logger()


class Mem0MemoryStore:
    """Wraps mem0.Memory to implement the MemoryStore protocol.

    The client is built on first use, not in ``__init__``. ``from_config``
    opens a connection to the vector store, so building it eagerly meant a
    pgvector outage at boot took the whole bot down with it — long-term memory
    is an enhancement to coaching, not a reason to stop tracking habits.
    """

    def __init__(self, config: dict) -> None:
        from mem0 import Memory

        self._memory_cls = Memory
        self._config = config
        self._memory: Any | None = None
        self._lock = asyncio.Lock()

    async def _client(self) -> Any:
        """Return the mem0 client, connecting on first use."""
        async with self._lock:
            if self._memory is None:
                self._memory = await asyncio.to_thread(self._memory_cls.from_config, self._config)
            return self._memory

    async def store_insight(self, user_id: int, insight: str, category: str) -> None:
        """Persist an insight for the given user, tagged with a category."""
        try:
            await self._store_insight_inner(user_id, insight, category)
        except Exception:
            logger.exception("mem0_store_error", user_id=user_id)

    @retry_store()
    async def _store_insight_inner(self, user_id: int, insight: str, category: str) -> None:
        memory = await self._client()
        await asyncio.to_thread(
            memory.add,
            insight,
            user_id=str(user_id),
            metadata={"category": category},
        )

    async def get_insights(self, user_id: int) -> list[MemoryInsight]:
        """Return all stored insights for the given user."""
        try:
            return await self._get_insights_inner(user_id)
        except Exception:
            logger.exception("mem0_get_error", user_id=user_id)
            return []

    @retry_store()
    async def _get_insights_inner(self, user_id: int) -> list[MemoryInsight]:
        memory = await self._client()
        results = await asyncio.to_thread(memory.get_all, user_id=str(user_id))
        return [
            MemoryInsight(
                content=m.get("memory", ""),
                category=m.get("metadata", {}).get("category", "general"),
                created_at=datetime.now(UTC),
            )
            for m in results.get("results", [])
        ]
```

- [ ] **Step 8: Run existing tests**

Run: `uv run pytest tests/unit/ -v --timeout=30`

Expected: all pass. The retry decorators are transparent to existing tests since they only activate on transient exceptions.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock \
  src/habit_tracker/infrastructure/resilience.py \
  src/habit_tracker/infrastructure/ai/llm_client.py \
  src/habit_tracker/infrastructure/memory/mem0_store.py \
  tests/unit/test_resilience.py
git commit -m "feat: add tenacity retry logic for LLM and store calls

retry_llm: 3 attempts, exponential backoff, retries rate limits and
connection errors only. retry_store: 2 attempts, shorter budget for
non-critical mem0/persistence calls."
```

---

### Task 4: Least-Privilege Database Role

**Files:**
- Modify: `infra/modules/keyvault/main.tf`
- Modify: `infra/modules/keyvault/outputs.tf`
- Modify: `infra/modules/postgres/variables.tf`
- Modify: `infra/modules/postgres/outputs.tf`
- Modify: `infra/live/postgres/terragrunt.hcl`
- Modify: `infra/live/web-app/terragrunt.hcl`
- Modify: `scripts/bootstrap-db-roles.sh`
- Modify: `src/habit_tracker/infrastructure/config/settings.py`
- Create: `alembic/versions/c3d4e5f6a7b8_add_bot_persistence_table.py`
- Modify: `src/habit_tracker/infrastructure/persistence/postgres_persistence.py`
- Modify: `tests/unit/test_settings.py`

**Interfaces:**
- Consumes: Key Vault outputs (`habit_app_db_password`), postgres outputs (split conn strings)
- Produces: `habit_tracker_app_connection_string` for the web app, `habit_tracker_admin_connection_string` for migration scripts, `mem0` schema config in Settings, `bot_persistence` table via Alembic

- [ ] **Step 1: Add `habit_app` password to Key Vault module**

In `infra/modules/keyvault/main.tf`, add after `random_password.phoenix_db`:

```hcl
resource "random_password" "habit_app" {
  length           = 40
  special          = true
  override_special = "-_.~"
}

resource "azurerm_key_vault_secret" "habit_app_db_password" {
  name         = "habit-app-db-password"
  value        = random_password.habit_app.result
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.terraform_kv_admin]
}
```

In `infra/modules/keyvault/outputs.tf`, add:

```hcl
output "habit_app_db_password" {
  description = "Password for the least-privilege habit_app database role (sensitive)"
  value       = random_password.habit_app.result
  sensitive   = true
}

output "habit_app_db_password_secret_uri" {
  description = "Key Vault secret URI for the habit_app database role password"
  value       = azurerm_key_vault_secret.habit_app_db_password.versionless_id
}
```

- [ ] **Step 2: Add `habit_app_db_password` to postgres module and split connection strings**

In `infra/modules/postgres/variables.tf`, add:

```hcl
variable "habit_app_db_password" {
  description = "Password for the least-privilege habit_app role (from Key Vault)"
  type        = string
  sensitive   = true
}
```

In `infra/modules/postgres/outputs.tf`, replace the existing `habit_tracker_connection_string` output with two outputs:

```hcl
output "habit_tracker_app_connection_string" {
  description = "asyncpg connection string using the least-privilege habit_app role"
  value       = "postgresql+asyncpg://habit_app:${var.habit_app_db_password}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/${azurerm_postgresql_flexible_server_database.habit_tracker.name}"
  sensitive   = true
}

output "habit_tracker_admin_connection_string" {
  description = "asyncpg connection string using the admin role (migrations only)"
  value       = "postgresql+asyncpg://${azurerm_postgresql_flexible_server.main.administrator_login}:${var.postgres_admin_password}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/${azurerm_postgresql_flexible_server_database.habit_tracker.name}"
  sensitive   = true
}
```

- [ ] **Step 3: Wire through Terragrunt live configs**

In `infra/live/postgres/terragrunt.hcl`, add to `inputs`:

```hcl
  habit_app_db_password = dependency.keyvault.outputs.habit_app_db_password
```

In `infra/live/web-app/terragrunt.hcl`, change:

```hcl
  postgres_connection_string = dependency.postgres.outputs.habit_tracker_connection_string
```

to:

```hcl
  postgres_connection_string = dependency.postgres.outputs.habit_tracker_app_connection_string
```

- [ ] **Step 4: Extend bootstrap-db-roles.sh to create `habit_app`**

In `scripts/bootstrap-db-roles.sh`, after retrieving `PHOENIX_DB_PASSWORD`, add:

```bash
HABIT_APP_PASSWORD=$(az keyvault secret show --vault-name "$KV_NAME" \
    --name "habit-app-db-password" --query value -o tsv)
```

After the Phoenix role creation and before the verification section, add the `habit_app` role:

```bash
echo "Creating habit_app role..."
run_sql "postgres" --set habit_app_pw="$HABIT_APP_PASSWORD" <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'habit_app') THEN
        CREATE ROLE habit_app LOGIN;
    END IF;
END
$$;
SQL

run_sql "postgres" --set habit_app_pw="$HABIT_APP_PASSWORD" \
    --command "ALTER ROLE habit_app WITH LOGIN PASSWORD :'habit_app_pw';"

echo "Granting habit_app access to the '$APP_DB' database..."
run_sql "postgres" <<SQL
GRANT CONNECT ON DATABASE "$APP_DB" TO habit_app;
SQL

run_sql "$APP_DB" <<'SQL'
GRANT USAGE ON SCHEMA public TO habit_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO habit_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO habit_app;
SQL

echo "Setting default privileges for future tables..."
run_sql "$APP_DB" <<'SQL'
ALTER DEFAULT PRIVILEGES FOR ROLE phoenixadmin IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO habit_app;
ALTER DEFAULT PRIVILEGES FOR ROLE phoenixadmin IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO habit_app;
SQL

echo "Creating mem0 schema owned by habit_app..."
run_sql "$APP_DB" <<'SQL'
CREATE SCHEMA IF NOT EXISTS mem0 AUTHORIZATION habit_app;
GRANT ALL PRIVILEGES ON SCHEMA mem0 TO habit_app;
ALTER DEFAULT PRIVILEGES FOR ROLE habit_app IN SCHEMA mem0
    GRANT ALL PRIVILEGES ON TABLES TO habit_app;
ALTER DEFAULT PRIVILEGES FOR ROLE habit_app IN SCHEMA mem0
    GRANT ALL PRIVILEGES ON SEQUENCES TO habit_app;
SQL
```

Add verification at the end, before the final success message:

```bash
echo "Verifying habit_app isolation..."
if PGPASSWORD="$HABIT_APP_PASSWORD" psql --host "$POSTGRES_HOST" --port 5432 \
    --username "habit_app" --dbname "$PHOENIX_DB" --no-psqlrc --quiet \
    --command "SELECT 1;" &> /dev/null; then
    echo -e "${RED}ERROR: habit_app can connect to $PHOENIX_DB${NC}"
    exit 1
fi
echo -e "${GREEN}✓ habit_app is denied access to $PHOENIX_DB${NC}"

if ! PGPASSWORD="$HABIT_APP_PASSWORD" psql --host "$POSTGRES_HOST" --port 5432 \
    --username "habit_app" --dbname "$APP_DB" --no-psqlrc --quiet \
    --command "SELECT 1;" &> /dev/null; then
    echo -e "${RED}ERROR: habit_app cannot connect to $APP_DB${NC}"
    exit 1
fi
echo -e "${GREEN}✓ habit_app can connect to $APP_DB${NC}"
```

- [ ] **Step 5: Add `bot_persistence` table to Alembic migration**

Create `alembic/versions/c3d4e5f6a7b8_add_bot_persistence_table.py`:

```python
"""add_bot_persistence_table

The bot_persistence table was previously created at runtime by
PostgresPersistence._ensure_table(). Moving it to Alembic lets the
least-privilege habit_app role operate without DDL permissions on
the public schema.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_persistence",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("data", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("bot_persistence")
```

- [ ] **Step 6: Remove `_ensure_table()` from PostgresPersistence**

In `src/habit_tracker/infrastructure/persistence/postgres_persistence.py`, delete the entire `_ensure_table` method (the method that runs `CREATE TABLE IF NOT EXISTS bot_persistence ...`) and remove its call from `_get_pool`. The resulting `_get_pool` should only create the connection pool:

```python
    async def _get_pool(self):
        if self._pool is None:
            import asyncpg

            ssl_context = None
            if ".database.azure.com" in self._database_url:
                from habit_tracker.infrastructure.database.connection import (
                    verified_ssl_context,
                )

                ssl_context = verified_ssl_context()

            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=1,
                max_size=3,
                ssl=ssl_context,
            )
        return self._pool
```

- [ ] **Step 7: Add `schema` to mem0 config in Settings**

In `src/habit_tracker/infrastructure/config/settings.py`, update `get_mem0_config()` to add the schema field:

```python
        return {
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "host": parsed.hostname or "localhost",
                    "port": parsed.port or 5432,
                    "user": urllib.parse.unquote(parsed.username) if parsed.username else "",
                    "password": password,
                    "dbname": (parsed.path or "/").lstrip("/"),
                    "schema": "mem0",
                },
            }
        }
```

- [ ] **Step 8: Write test for mem0 schema config**

In `tests/unit/test_settings.py`, add:

```python
class TestMem0SchemaIsolation:
    def test_mem0_config_uses_mem0_schema(self, monkeypatch) -> None:
        """mem0 tables live in their own schema, not public."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@host:5432/db")
        config = Settings().get_mem0_config()["vector_store"]["config"]

        assert config["schema"] == "mem0"
```

- [ ] **Step 9: Run tests**

Run: `uv run pytest tests/unit/test_settings.py tests/integration/test_postgres_persistence.py -v`

Expected: all pass

- [ ] **Step 10: Commit**

```bash
git add infra/modules/keyvault/main.tf infra/modules/keyvault/outputs.tf \
  infra/modules/postgres/variables.tf infra/modules/postgres/outputs.tf \
  infra/live/postgres/terragrunt.hcl infra/live/web-app/terragrunt.hcl \
  scripts/bootstrap-db-roles.sh \
  alembic/versions/c3d4e5f6a7b8_add_bot_persistence_table.py \
  src/habit_tracker/infrastructure/persistence/postgres_persistence.py \
  src/habit_tracker/infrastructure/config/settings.py \
  tests/unit/test_settings.py
git commit -m "feat: least-privilege habit_app role for runtime bot

Runtime container uses habit_app (CRUD-only on public, full DDL on mem0
schema). Admin credential is used only by Alembic during deploy scripts.
bot_persistence table moves from runtime DDL to Alembic migration."
```

---

### Task 5: PostgresPersistence Per-User Row Stabilization

**Files:**
- Modify: `src/habit_tracker/infrastructure/persistence/postgres_persistence.py`
- Create: `alembic/versions/d4e5f6a7b8c9_split_persistence_blobs.py`
- Modify: `tests/integration/test_postgres_persistence.py`

**Interfaces:**
- Consumes: `retry_store()` from Task 3, `bot_persistence` table from Task 4
- Produces: same `BasePersistence` API — PTB compatibility unchanged

- [ ] **Step 1: Update the mock helper for per-key storage**

In `tests/integration/test_postgres_persistence.py`, replace `_make_mock_pool`:

```python
def _make_mock_pool(rows_by_key: dict | None = None):
    """Build a mock asyncpg pool that stores data in memory with per-key rows."""
    if rows_by_key is None:
        rows_by_key = {}

    store = dict(rows_by_key)

    def make_conn():
        conn = AsyncMock()

        async def fetchrow(sql, *args):
            if args:
                key = args[0]
                if key in store:
                    return {"data": store[key]}
            return None

        async def fetch(sql, *args):
            if "LIKE" in sql and args:
                prefix = args[0].replace("%", "")
                return [
                    {"key": k, "data": v}
                    for k, v in store.items()
                    if k.startswith(prefix)
                ]
            return []

        async def execute(sql, *args):
            if "INSERT INTO" in sql or "ON CONFLICT" in sql:
                key, json_str, *_ = args
                store[key] = json.loads(json_str) if isinstance(json_str, str) else json_str
            elif "DELETE" in sql and args:
                key = args[0]
                store.pop(key, None)

        conn.fetchrow = fetchrow
        conn.fetch = fetch
        conn.execute = execute
        return conn

    class FakeAcquireCtx:
        def __init__(self):
            self._conn = make_conn()

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *exc):
            pass

    pool = MagicMock()
    pool.acquire = FakeAcquireCtx
    pool.close = AsyncMock()

    return pool, store
```

- [ ] **Step 2: Run existing tests to see them fail**

Run: `uv run pytest tests/integration/test_postgres_persistence.py -v`

Expected: tests that depend on the old single-blob pattern will fail after the implementation change.

- [ ] **Step 3: Rewrite PostgresPersistence to use per-key rows**

Replace the full contents of `src/habit_tracker/infrastructure/persistence/postgres_persistence.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

import structlog
from telegram.ext import BasePersistence, PersistenceInput

logger = structlog.get_logger()


class PostgresPersistence(BasePersistence):
    def __init__(self, database_url: str) -> None:
        super().__init__(
            store_data=PersistenceInput(
                bot_data=False,
                chat_data=True,
                user_data=True,
                callback_data=False,
            ),
        )
        url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        self._database_url = url.split("?", 1)[0]
        self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            import asyncpg

            ssl_context = None
            if ".database.azure.com" in self._database_url:
                from habit_tracker.infrastructure.database.connection import (
                    verified_ssl_context,
                )

                ssl_context = verified_ssl_context()

            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=1,
                max_size=3,
                ssl=ssl_context,
            )
        return self._pool

    async def _load_one(self, key: str) -> dict:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT data FROM bot_persistence WHERE key = $1", key)
            if row:
                data = row["data"]
                return json.loads(data) if isinstance(data, str) else data
            return {}

    async def _load_prefixed(self, prefix: str) -> dict[int, dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, data FROM bot_persistence WHERE key LIKE $1",
                f"{prefix}:%",
            )
            result = {}
            for row in rows:
                suffix = row["key"].split(":", 1)[1]
                data = row["data"]
                result[int(suffix)] = json.loads(data) if isinstance(data, str) else data
            return result

    async def _save(self, key: str, data: dict) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_persistence (key, data, updated_at) VALUES ($1, $2::jsonb, $3)
                ON CONFLICT (key) DO UPDATE SET data = $2::jsonb, updated_at = $3
            """,
                key,
                json.dumps(data, default=str),
                datetime.now(UTC),
            )

    async def _delete(self, key: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM bot_persistence WHERE key = $1", key)

    async def get_bot_data(self) -> dict:
        return await self._load_one("bot_data")

    async def update_bot_data(self, data: dict) -> None:
        await self._save("bot_data", data)

    async def refresh_bot_data(self, bot_data: dict) -> dict:
        return await self._load_one("bot_data")

    async def get_chat_data(self) -> dict[int, dict]:
        return await self._load_prefixed("chat_data")

    async def update_chat_data(self, chat_id: int, data: dict) -> None:
        await self._save(f"chat_data:{chat_id}", data)

    async def refresh_chat_data(self, chat_id: int, chat_data: dict) -> dict:
        return await self._load_one(f"chat_data:{chat_id}")

    async def get_user_data(self) -> dict[int, dict]:
        return await self._load_prefixed("user_data")

    async def update_user_data(self, user_id: int, data: dict) -> None:
        await self._save(f"user_data:{user_id}", data)

    async def refresh_user_data(self, user_id: int, user_data: dict) -> dict:
        return await self._load_one(f"user_data:{user_id}")

    async def get_callback_data(self) -> Any:
        return None

    async def update_callback_data(self, data: Any) -> None:
        pass

    async def get_conversations(self, name: str) -> dict:
        return {}

    async def update_conversation(self, name: str, key: tuple, new_state: Any) -> None:
        pass

    async def drop_chat_data(self, chat_id: int) -> None:
        await self._delete(f"chat_data:{chat_id}")

    async def drop_user_data(self, user_id: int) -> None:
        await self._delete(f"user_data:{user_id}")

    async def flush(self) -> None:
        pass

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
```

- [ ] **Step 4: Run persistence tests**

Run: `uv run pytest tests/integration/test_postgres_persistence.py -v`

Expected: all PASS with the updated mock

- [ ] **Step 5: Create Alembic migration to split legacy blobs**

Create `alembic/versions/d4e5f6a7b8c9_split_persistence_blobs.py`:

```python
"""split_persistence_blobs

Splits the legacy single-row user_data and chat_data blobs into per-key
rows. After this migration, each user and chat has its own row keyed as
'user_data:{id}' and 'chat_data:{id}' respectively.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-31 00:00:01.000000

"""

from collections.abc import Sequence

import json

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _split_blob(conn, blob_key: str, prefix: str) -> None:
    """Read a legacy blob row, insert per-ID rows, delete the blob."""
    row = conn.execute(
        sa.text("SELECT data FROM bot_persistence WHERE key = :key"),
        {"key": blob_key},
    ).fetchone()
    if row is None:
        return

    data = row[0]
    if isinstance(data, str):
        data = json.loads(data)

    for item_id, item_data in data.items():
        conn.execute(
            sa.text(
                "INSERT INTO bot_persistence (key, data, updated_at) "
                "VALUES (:key, :data::jsonb, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET data = :data::jsonb, updated_at = NOW()"
            ),
            {"key": f"{prefix}:{item_id}", "data": json.dumps(item_data, default=str)},
        )

    conn.execute(
        sa.text("DELETE FROM bot_persistence WHERE key = :key"),
        {"key": blob_key},
    )


def upgrade() -> None:
    conn = op.get_bind()
    _split_blob(conn, "user_data", "user_data")
    _split_blob(conn, "chat_data", "chat_data")


def downgrade() -> None:
    pass
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/ -v --timeout=60`

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/habit_tracker/infrastructure/persistence/postgres_persistence.py \
  alembic/versions/d4e5f6a7b8c9_split_persistence_blobs.py \
  tests/integration/test_postgres_persistence.py
git commit -m "feat: per-user row storage for PostgresPersistence

Each user/chat gets its own row (user_data:{id}, chat_data:{id}).
Eliminates read-modify-write race between concurrent check-ins.
Alembic migration splits any legacy single-blob rows."
```
