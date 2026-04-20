from __future__ import annotations

import json
import logging
import re

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.github_publish_config import GitHubPublishConfig
from app.repositories.github_publish_config_repository import GitHubPublishConfigRepository
from pydantic import ValidationError

from app.schemas.github_publish_config import (
    GitHubPublishConfigUpdateRequest,
    normalize_namespace_isolation_defaults,
)

_VALID_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
_VALID_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
_VALID_BASE_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._/-]{0,159}$")
_VALID_TARGET_ENVIRONMENT_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_VALID_GKE_CLUSTER_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,118}$")
_VALID_GKE_CLUSTER_LOCATION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,118}$")
_VALID_GCP_PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_DEFAULT_DEPLOY_WORKFLOW_MODE = "site_repo_template_v1"
_DEFAULT_TARGET_ENVIRONMENT_KEY = "gke_prod"
_TARGET_ENVIRONMENT_SOURCE_ADMIN = "admin_config"
_DEFAULT_NAMESPACE_ISOLATION_DEFAULTS = normalize_namespace_isolation_defaults(None).model_dump(mode="json")
_ALLOWED_DEPLOY_WORKFLOW_MODES = {
    "site_repo_template_v1",
}

logger = logging.getLogger(__name__)


class GitHubPublishConfigValidationError(ValueError):
    pass


def _normalize_base_path(value: object) -> str:
    normalized = str(value or "/").strip() or "/"
    normalized = normalized.replace("\\", "/")
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    if len(normalized) > 1 and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized or "/"


class GitHubPublishConfigService:
    def __init__(
        self,
        *,
        session: Session,
        repository: GitHubPublishConfigRepository,
    ) -> None:
        self.session = session
        self.repository = repository

    def get(self) -> GitHubPublishConfig:
        existing = self.repository.get_singleton()
        if existing is not None:
            return existing
        return GitHubPublishConfig(
            repository="",
            default_branch="main",
            base_path="/",
            deploy_workflow_mode=_DEFAULT_DEPLOY_WORKFLOW_MODE,
            target_environment_key=_DEFAULT_TARGET_ENVIRONMENT_KEY,
            target_environment_source=_TARGET_ENVIRONMENT_SOURCE_ADMIN,
            managed_gke_cluster_name=None,
            managed_gke_cluster_location=None,
            managed_gke_project_id=None,
            namespace_isolation_defaults_json=dict(_DEFAULT_NAMESPACE_ISOLATION_DEFAULTS),
            enabled=False,
        )

    @staticmethod
    def _emit_structured_log(*, payload: dict[str, object], fallback_message: str, level: int) -> None:
        try:
            message = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        except (TypeError, ValueError):
            message = fallback_message
        logger.log(level, message, extra={"json_fields": payload})

    def update(
        self,
        *,
        payload: GitHubPublishConfigUpdateRequest,
        actor_principal_id: str | None = None,
        actor_business_id: str | None = None,
    ) -> GitHubPublishConfig:
        owner = ((payload.owner or payload.repository) or "").strip()
        raw_default_branch = (payload.default_branch or "").strip()
        default_branch = raw_default_branch or "main"
        base_path = _normalize_base_path(payload.base_path)
        deploy_workflow_mode = str(payload.deploy_workflow_mode or "").strip().lower() or _DEFAULT_DEPLOY_WORKFLOW_MODE
        target_environment_key = (
            str(payload.target_environment_key or "").strip().lower() or _DEFAULT_TARGET_ENVIRONMENT_KEY
        )
        target_environment_source = _TARGET_ENVIRONMENT_SOURCE_ADMIN
        enabled = bool(payload.enabled)
        existing = self.repository.get_singleton()
        payload_fields_set = getattr(payload, "model_fields_set", set()) or set()
        managed_cluster_name_provided = "managed_gke_cluster_name" in payload_fields_set
        managed_cluster_location_provided = "managed_gke_cluster_location" in payload_fields_set
        managed_project_id_provided = "managed_gke_project_id" in payload_fields_set
        managed_gke_cluster_name = (
            str(payload.managed_gke_cluster_name or "").strip().lower() or None
        )
        managed_gke_cluster_location = (
            str(payload.managed_gke_cluster_location or "").strip().lower() or None
        )
        managed_gke_project_id = (
            str(payload.managed_gke_project_id or "").strip().lower() or None
        )
        if not managed_cluster_name_provided and existing is not None:
            managed_gke_cluster_name = (
                str(getattr(existing, "managed_gke_cluster_name", "") or "").strip().lower() or None
            )
        if not managed_cluster_location_provided and existing is not None:
            managed_gke_cluster_location = (
                str(getattr(existing, "managed_gke_cluster_location", "") or "").strip().lower() or None
            )
        if not managed_project_id_provided and existing is not None:
            managed_gke_project_id = (
                str(getattr(existing, "managed_gke_project_id", "") or "").strip().lower() or None
            )
        raw_namespace_defaults = payload.namespace_isolation_defaults
        if raw_namespace_defaults is None and existing is not None:
            raw_namespace_defaults = existing.namespace_isolation_defaults_json
        try:
            namespace_isolation_defaults = normalize_namespace_isolation_defaults(
                raw_namespace_defaults
            ).model_dump(mode="json")
        except ValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else {}
            location = ".".join(str(item) for item in first_error.get("loc", ()))
            detail = str(first_error.get("msg") or "Invalid namespace isolation defaults.")
            if location:
                raise GitHubPublishConfigValidationError(
                    f"Namespace isolation defaults are invalid at '{location}': {detail}"
                ) from exc
            raise GitHubPublishConfigValidationError(
                f"Namespace isolation defaults are invalid: {detail}"
            ) from exc

        if enabled and not owner:
            raise GitHubPublishConfigValidationError("GitHub owner is required when GitHub publishing is enabled.")
        if owner and not _VALID_OWNER_PATTERN.fullmatch(owner):
            raise GitHubPublishConfigValidationError(
                "GitHub owner is invalid. Use a GitHub account/organization name (for example: mhanson13)."
            )
        if enabled and not raw_default_branch:
            raise GitHubPublishConfigValidationError("Default branch is required when GitHub publishing is enabled.")
        if (
            not _VALID_BRANCH_PATTERN.fullmatch(default_branch)
            or ".." in default_branch
            or default_branch.startswith("/")
            or default_branch.endswith("/")
            or "//" in default_branch
        ):
            raise GitHubPublishConfigValidationError(
                "Default branch is invalid. Use letters, numbers, ., _, -, or / only."
            )
        if not _VALID_BASE_PATH_PATTERN.fullmatch(base_path) or ".." in base_path:
            raise GitHubPublishConfigValidationError(
                "Base path is invalid. Use '/' or '/subpath' with letters, numbers, -, _, ., and /."
            )
        if deploy_workflow_mode not in _ALLOWED_DEPLOY_WORKFLOW_MODES:
            raise GitHubPublishConfigValidationError(
                "Deploy workflow mode is invalid. Use an approved platform-managed template mode."
            )
        if not _VALID_TARGET_ENVIRONMENT_KEY_PATTERN.fullmatch(target_environment_key):
            raise GitHubPublishConfigValidationError(
                "Target environment key is invalid. Use lowercase letters, numbers, '-' or '_'."
            )
        if managed_gke_cluster_name and not _VALID_GKE_CLUSTER_NAME_PATTERN.fullmatch(managed_gke_cluster_name):
            raise GitHubPublishConfigValidationError(
                "Managed GKE cluster name is invalid. Use lowercase letters, numbers, and '-'."
            )
        if managed_gke_cluster_location and not _VALID_GKE_CLUSTER_LOCATION_PATTERN.fullmatch(
            managed_gke_cluster_location
        ):
            raise GitHubPublishConfigValidationError(
                "Managed GKE cluster location is invalid. Use lowercase letters, numbers, and '-'."
            )
        if managed_gke_project_id and not _VALID_GCP_PROJECT_ID_PATTERN.fullmatch(managed_gke_project_id):
            raise GitHubPublishConfigValidationError(
                "Managed GKE project id is invalid. Use a valid Google Cloud project id."
            )

        previous_values = {
            "owner": (existing.repository if existing is not None else ""),
            "default_branch": (existing.default_branch if existing is not None else "main"),
            "base_path": (existing.base_path if existing is not None else "/"),
            "deploy_workflow_mode": (
                existing.deploy_workflow_mode if existing is not None else _DEFAULT_DEPLOY_WORKFLOW_MODE
            ),
            "target_environment_key": (
                existing.target_environment_key if existing is not None else _DEFAULT_TARGET_ENVIRONMENT_KEY
            ),
            "target_environment_source": (
                existing.target_environment_source if existing is not None else _TARGET_ENVIRONMENT_SOURCE_ADMIN
            ),
            "managed_gke_cluster_name": (
                existing.managed_gke_cluster_name if existing is not None else None
            ),
            "managed_gke_cluster_location": (
                existing.managed_gke_cluster_location if existing is not None else None
            ),
            "managed_gke_project_id": (
                existing.managed_gke_project_id if existing is not None else None
            ),
            "namespace_isolation_defaults": (
                normalize_namespace_isolation_defaults(
                    existing.namespace_isolation_defaults_json if existing is not None else None
                ).model_dump(mode="json")
            ),
            "enabled": bool(existing.enabled) if existing is not None else False,
        }
        updated_values = {
            "owner": owner,
            "default_branch": default_branch,
            "base_path": base_path,
            "deploy_workflow_mode": deploy_workflow_mode,
            "target_environment_key": target_environment_key,
            "target_environment_source": target_environment_source,
            "managed_gke_cluster_name": managed_gke_cluster_name,
            "managed_gke_cluster_location": managed_gke_cluster_location,
            "managed_gke_project_id": managed_gke_project_id,
            "namespace_isolation_defaults": namespace_isolation_defaults,
            "enabled": enabled,
        }

        if existing is None:
            existing = GitHubPublishConfig(
                repository=owner,
                default_branch=default_branch,
                base_path=base_path,
                deploy_workflow_mode=deploy_workflow_mode,
                target_environment_key=target_environment_key,
                target_environment_source=target_environment_source,
                managed_gke_cluster_name=managed_gke_cluster_name,
                managed_gke_cluster_location=managed_gke_cluster_location,
                managed_gke_project_id=managed_gke_project_id,
                namespace_isolation_defaults_json=namespace_isolation_defaults,
                enabled=enabled,
            )
        else:
            existing.repository = owner
            existing.default_branch = default_branch
            existing.base_path = base_path
            existing.deploy_workflow_mode = deploy_workflow_mode
            existing.target_environment_key = target_environment_key
            existing.target_environment_source = target_environment_source
            existing.managed_gke_cluster_name = managed_gke_cluster_name
            existing.managed_gke_cluster_location = managed_gke_cluster_location
            existing.managed_gke_project_id = managed_gke_project_id
            existing.namespace_isolation_defaults_json = namespace_isolation_defaults
            existing.enabled = enabled
        self.repository.save(existing)
        self.session.commit()
        self.session.refresh(existing)
        changed_fields = [
            field_name
            for field_name in (
                "owner",
                "default_branch",
                "base_path",
                "deploy_workflow_mode",
                "target_environment_key",
                "target_environment_source",
                "managed_gke_cluster_name",
                "managed_gke_cluster_location",
                "managed_gke_project_id",
                "namespace_isolation_defaults",
                "enabled",
            )
            if previous_values.get(field_name) != updated_values.get(field_name)
        ]
        changed_values = {
            field_name: {
                "previous": previous_values.get(field_name),
                "current": updated_values.get(field_name),
            }
            for field_name in changed_fields
        }
        self._emit_structured_log(
            payload={
                "event": "admin_github_publish_config_updated",
                "timestamp": utc_now().isoformat(),
                "actor_principal_id": (actor_principal_id or "").strip() or None,
                "actor_business_id": (actor_business_id or "").strip() or None,
                "changed_fields": changed_fields,
                "changed_values": changed_values,
                "effective_target": {
                    "owner": existing.repository,
                    "repository": existing.repository,
                    "default_branch": existing.default_branch,
                    "base_path": existing.base_path,
                    "deploy_workflow_mode": existing.deploy_workflow_mode,
                    "target_environment_key": existing.target_environment_key,
                    "target_environment_source": existing.target_environment_source,
                    "managed_gke_cluster_name": existing.managed_gke_cluster_name,
                    "managed_gke_cluster_location": existing.managed_gke_cluster_location,
                    "managed_gke_project_id": existing.managed_gke_project_id,
                    "namespace_isolation_defaults": normalize_namespace_isolation_defaults(
                        existing.namespace_isolation_defaults_json
                    ).model_dump(mode="json"),
                    "enabled": bool(existing.enabled),
                },
            },
            fallback_message="admin_github_publish_config_updated",
            level=logging.INFO,
        )
        return existing
