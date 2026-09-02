from __future__ import annotations

from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).parents[2]
WORKFLOW_DIR = PROJECT_ROOT / ".github" / "workflows"


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text()


def test_pull_request_workflow_never_receives_production_credentials() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "infra-plan:" not in workflow
    assert "environment: production" not in workflow
    assert "id-token: write" not in workflow
    assert "secrets." not in workflow


def test_all_actions_use_immutable_commit_references() -> None:
    action_pattern = re.compile(r"^\s*- uses:\s*[^\s@]+@([0-9a-f]{40})(?:\s+#\s+v\S+)?$", re.MULTILINE)

    for workflow_path in WORKFLOW_DIR.glob("*.yml"):
        workflow = workflow_path.read_text()
        uses_lines = [line for line in workflow.splitlines() if re.match(r"^\s*- uses:", line)]
        pinned_lines = action_pattern.findall(workflow)
        assert len(pinned_lines) == len(uses_lines), f"mutable action reference in {workflow_path.name}"

    workflows = "\n".join(path.read_text() for path in WORKFLOW_DIR.glob("*.yml"))
    assert "azure/login@532459ea530d8321f2fb9bb10d1e0bcf23869a43" in workflows
    assert "azure/login@93381592711f247e165c389ebb30b596c84cdc48" not in workflows


def test_workflow_tool_versions_are_pinned() -> None:
    workflows = "\n".join(path.read_text() for path in WORKFLOW_DIR.glob("*.yml"))

    assert "terragrunt-version: latest" not in workflows
    assert workflows.count('version: "0.11.30"') == workflows.count("uses: astral-sh/setup-uv@")
    assert workflows.count("tofu_version: 1.12.1") == workflows.count("uses: opentofu/setup-opentofu@")


def test_checkout_credentials_are_never_persisted() -> None:
    for workflow_path in WORKFLOW_DIR.glob("*.yml"):
        workflow = workflow_path.read_text()
        checkout_count = workflow.count("uses: actions/checkout@")
        assert workflow.count("persist-credentials: false") == checkout_count


def test_deploy_uses_native_groq_model_and_tracks_startup_script() -> None:
    workflow = _read(".github/workflows/deploy.yml")

    assert "groq/qwen/qwen3.6-27b" not in workflow
    assert "qwen/qwen3.6-27b" in workflow
    assert 'if [[ "$LLM_MODEL" == groq/* ]]' in workflow
    assert "scripts/startup.sh" in workflow


def test_web_app_identity_has_vault_level_secret_reader() -> None:
    module = _read("infra/modules/web-app/main.tf")

    assert "scope                = data.azurerm_key_vault.main.id" in module
    assert '"Key Vault Secrets User"' in module


def test_web_app_uses_managed_identity_to_pull_from_private_acr() -> None:
    module = _read("infra/modules/web-app/main.tf")

    assert "container_registry_use_managed_identity = true" in module


def test_runtime_container_uses_a_numeric_non_root_user() -> None:
    dockerfile = _read("Dockerfile")

    assert re.search(r"^USER\s+(?!0(?:\D|$))\d+(?::\d+)?$", dockerfile, re.MULTILINE)


def test_container_base_images_are_digest_pinned() -> None:
    dockerfile = _read("Dockerfile")
    base_images = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]

    assert base_images
    assert all(re.search(r"@sha256:[0-9a-f]{64}(?:\s|$)", image) for image in base_images)
