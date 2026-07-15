from __future__ import annotations

import base64
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
import pkgutil
import ssl
from typing import Any
import urllib.parse

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models
from app.db.base import Base
from app.integrations.seo_migration_github_publisher import (
    SEOMigrationGitHubPublisherError,
    derive_site_preview_backend_config_name,
    derive_site_preview_certificate_name,
    derive_site_preview_frontend_config_name,
    _request_google_json,
    _request_kubernetes_json,
    _resolve_google_access_token_for_managed_deploy_operations,
    _validate_managed_deploy_impersonation_service_account_email,
)
from app.models.seo_site import SEOSite
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.services.github_publish_config import GitHubPublishConfigSecretError
from app.services.seo_migration import SEOMigrationService
from app.services.seo_sites import SEOSiteNotFoundError

_MBSRN_MANAGED_LABEL = "mbsrn"
_MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME = "ghcr-pull-secret"
_MBSRN_RESOURCE_QUOTA_NAME = "site-resources"
_MBSRN_LIMIT_RANGE_NAME = "site-container-limits"
_MBSRN_NETWORK_POLICY_NAMES = (
    "site-default-deny-ingress",
    "site-web-allow-managed-ingress",
)
_SITE_DELETE_EXTERNAL_VERIFICATION_LIMITED = "site_delete_external_verification_limited"
_SITE_DELETE_GIT_REPO_VERIFICATION_LIMITED = "site_delete_git_repo_verification_limited"
_SITE_DELETE_RUNTIME_VERIFICATION_LIMITED = "site_delete_runtime_verification_limited"
_SITE_DELETE_STATIC_IP_VERIFICATION_LIMITED = "site_delete_static_ip_verification_limited"
_SITE_DELETE_STATIC_IP_SHARED_GATEWAY_NOT_AUTO_DELETED = "site_delete_static_ip_shared_gateway_not_auto_deleted"
_SITE_DELETE_DNS_VERIFICATION_LIMITED = "site_delete_dns_verification_limited"
_SITE_DELETE_MANAGED_CERTIFICATE_VERIFICATION_LIMITED = "site_delete_managed_certificate_verification_limited"
_GITHUB_REPO_DELETE_PROTECTED_CONTROL_PLANE_REPO_BLOCKED = (
    "github_repo_delete_protected_control_plane_repo_blocked"
)


@dataclass(frozen=True)
class _DeleteIssue:
    reason_code: str
    message: str


@dataclass(frozen=True)
class _DeleteResource:
    resource_type: str
    status: str
    summary: str
    reason_code: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": self.resource_type,
            "status": self.status,
            "reason_code": self.reason_code,
            "summary": self.summary,
            "details": dict(self.details or {}),
        }


@dataclass(frozen=True)
class _DeleteContext:
    site_id: str
    repo_owner: str | None
    repo_name: str | None
    repo_ref: str
    admin_repo_owner: str | None
    kubernetes_namespace: str | None
    preview_hostname: str | None
    static_ip_name: str | None
    managed_certificate_name: str | None
    dns_record_name: str | None
    dns_managed_zone: str | None
    dns_project_id: str | None
    dns_ttl: int
    managed_gke_config: dict[str, str | None]
    namespace_isolation_defaults: dict[str, object] | None
    uses_shared_preview_gateway: bool


@dataclass(frozen=True)
class _ClusterAccess:
    cluster_endpoint: str
    ssl_context: ssl.SSLContext
    access_token: str
    timeout_seconds: int


class SEOSiteDeleteError(ValueError):
    def __init__(
        self,
        *,
        status_code: int,
        reason_code: str,
        message: str,
        blockers: list[dict[str, str]] | None = None,
        warnings: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason_code = reason_code
        self.message = message
        self.blockers = blockers or []
        self.warnings = warnings or []

    def to_detail(self) -> dict[str, object]:
        return {
            "reason_code": self.reason_code,
            "message": self.message,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


def _normalize_text(value: object, *, max_length: int = 500) -> str | None:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        return normalized[:max_length]
    return normalized


def _normalize_repo_owner(value: object) -> str | None:
    normalized = _normalize_text(value, max_length=120)
    if not normalized:
        return None
    if "/" in normalized:
        normalized = normalized.split("/", 1)[0].strip()
    return normalized or None


def _normalize_repo_full_name(value: object, *, max_length: int = 255) -> str | None:
    normalized = _normalize_text(value, max_length=max_length)
    if not normalized:
        return None
    normalized = normalized.replace("\\", "/").strip().strip("/")
    parts = [part.strip().lower() for part in normalized.split("/")]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    if any(" " in part for part in parts):
        return None
    return f"{parts[0]}/{parts[1]}"


def _normalize_hostname(value: object) -> str | None:
    normalized = _normalize_text(value, max_length=253)
    if not normalized:
        return None
    return normalized.lower().rstrip(".")


def _identifier_fragment(value: object, *, fallback: str = "", max_length: int = 80) -> str:
    raw = str(value or "").strip().lower()
    cleaned = "".join(character if character.isalnum() else "-" for character in raw)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length]


def _issue(reason_code: str, message: str) -> dict[str, str]:
    return {
        "reason_code": reason_code,
        "message": message,
    }


def _resource(
    resource_type: str,
    status: str,
    summary: str,
    *,
    reason_code: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _DeleteResource(
        resource_type=resource_type,
        status=status,
        summary=summary,
        reason_code=reason_code,
        details=details,
    ).to_dict()


def _category_for_model(model: type[Any]) -> str:
    model_name = getattr(model, "__name__", "")
    if model_name.startswith("SEOMigration"):
        return "migration"
    if model_name.startswith("SEOAudit"):
        return "audits"
    if model_name.startswith("SEORecommendation"):
        return "recommendations"
    if model_name.startswith("SEOAutomation"):
        return "automation"
    if model_name.startswith("SEOAction"):
        return "actions"
    if model_name.startswith("SEOCompetitor"):
        return "competitors"
    return "site_owned"


class SEOSiteDeleteService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_site_repository: SEOSiteRepository,
        seo_migration_service: SEOMigrationService,
        protected_control_plane_repository: str,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_site_repository = seo_site_repository
        self.seo_migration_service = seo_migration_service
        self.protected_control_plane_repository = protected_control_plane_repository

    def build_delete_plan(
        self,
        *,
        business_id: str,
        site_id: str,
        force_delete_active: bool = False,
    ) -> dict[str, Any]:
        self._require_business(business_id)
        site = self._require_site(business_id=business_id, site_id=site_id)
        dependency_payload, dependency_total = self._build_dependency_summary(
            business_id=business_id,
            site_id=site_id,
        )
        context = self._build_delete_context(site=site, business_id=business_id)
        gcp_deploy_key, key_warning = self._load_managed_gcp_deploy_key()

        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        if key_warning is not None:
            warnings.append(key_warning)
        if site.is_active and not force_delete_active:
            blockers.append(
                _issue(
                    "site_delete_active_site_blocked",
                    "This site is active. Deactivate it first or enable force delete for active sites during execution.",
                )
            )

        github_resource, github_blockers, github_warnings = self._plan_github_repo_resource(
            context=context,
            business_id=business_id,
            site_id=site_id,
        )
        runtime_resource, runtime_blockers, runtime_warnings = self._plan_runtime_resource(
            context=context,
            gcp_deploy_key=gcp_deploy_key,
        )
        static_ip_resource, static_ip_blockers, static_ip_warnings = self._plan_static_ip_resource(
            context=context,
            gcp_deploy_key=gcp_deploy_key,
        )
        dns_resource, dns_blockers, dns_warnings = self._plan_dns_resource(
            context=context,
            static_ip_resource=static_ip_resource,
            gcp_deploy_key=gcp_deploy_key,
        )
        managed_certificate_resource, certificate_blockers, certificate_warnings = self._plan_managed_certificate_resource(
            context=context,
            site=site,
            gcp_deploy_key=gcp_deploy_key,
        )

        blockers.extend(github_blockers)
        blockers.extend(runtime_blockers)
        blockers.extend(static_ip_blockers)
        blockers.extend(dns_blockers)
        blockers.extend(certificate_blockers)

        warnings.extend(github_warnings)
        warnings.extend(runtime_warnings)
        warnings.extend(static_ip_warnings)
        warnings.extend(dns_warnings)
        warnings.extend(certificate_warnings)

        confirmation_phrase = self._build_confirmation_phrase(site=site, context=context)
        expected_dns_records: list[dict[str, Any]] = []
        if context.dns_record_name:
            expected_dns_records.append(
                {
                    "record_name": context.dns_record_name,
                    "record_type": "A",
                    "managed_zone": context.dns_managed_zone,
                    "project_id": context.dns_project_id,
                    "expected_value": (static_ip_resource.get("details") or {}).get("observed_address"),
                }
            )

        return {
            "reason_code": "site_delete_plan_ready",
            "site_id": site.id,
            "site_name": site.display_name,
            "domain": site.normalized_domain,
            "is_active": bool(site.is_active),
            "generated_repo_owner": context.repo_owner,
            "generated_repo_name": context.repo_name,
            "kubernetes_namespace": context.kubernetes_namespace,
            "preview_hostname": context.preview_hostname,
            "static_ip_name": context.static_ip_name,
            "managed_certificate_name": context.managed_certificate_name,
            "dns_records_expected": expected_dns_records,
            "db_dependency_total": dependency_total,
            "db_dependencies": dependency_payload,
            "external_resources": [
                github_resource,
                runtime_resource,
                dns_resource,
                static_ip_resource,
                managed_certificate_resource,
            ],
            "blockers": blockers,
            "warnings": warnings,
            "required_confirmation_phrase": confirmation_phrase,
            "execution_defaults": {
                "delete_github_repo": False,
                "delete_runtime_resources": False,
                "delete_dns_resources": False,
                "force_delete_active": False,
            },
        }

    def execute_delete(
        self,
        *,
        business_id: str,
        site_id: str,
        confirmation_phrase: str,
        acknowledge_delete_database_records: bool,
        delete_github_repo: bool,
        acknowledge_delete_github_repo: bool,
        delete_runtime_resources: bool,
        acknowledge_delete_runtime_resources: bool,
        delete_dns_resources: bool,
        acknowledge_delete_dns_resources: bool,
        force_delete_active: bool,
    ) -> dict[str, Any]:
        plan = self.build_delete_plan(
            business_id=business_id,
            site_id=site_id,
            force_delete_active=force_delete_active,
        )
        site = self._require_site(business_id=business_id, site_id=site_id)
        context = self._build_delete_context(site=site, business_id=business_id)
        gcp_deploy_key, key_warning = self._load_managed_gcp_deploy_key()

        if not acknowledge_delete_database_records:
            raise SEOSiteDeleteError(
                status_code=422,
                reason_code="site_delete_confirmation_required",
                message="Database deletion acknowledgement is required before permanent delete can run.",
                blockers=[_issue("site_delete_confirmation_required", "Acknowledge control-plane database deletion.")],
            )
        if confirmation_phrase.strip() != str(plan.get("required_confirmation_phrase") or "").strip():
            raise SEOSiteDeleteError(
                status_code=422,
                reason_code="site_delete_confirmation_mismatch",
                message="Confirmation phrase did not match the required site delete phrase.",
                blockers=[_issue("site_delete_confirmation_mismatch", "Confirmation phrase mismatch.")],
            )
        if site.is_active and not force_delete_active:
            raise SEOSiteDeleteError(
                status_code=409,
                reason_code="site_delete_active_site_blocked",
                message="Active sites must be deactivated first or explicitly force deleted.",
                blockers=[_issue("site_delete_active_site_blocked", "Active site delete requires force confirmation.")],
            )
        if delete_github_repo and not acknowledge_delete_github_repo:
            raise SEOSiteDeleteError(
                status_code=422,
                reason_code="site_delete_confirmation_required",
                message="GitHub repository deletion acknowledgement is required before execution.",
                blockers=[_issue("site_delete_confirmation_required", "Acknowledge GitHub repository deletion.")],
            )
        if delete_runtime_resources and not acknowledge_delete_runtime_resources:
            raise SEOSiteDeleteError(
                status_code=422,
                reason_code="site_delete_confirmation_required",
                message="Runtime resource deletion acknowledgement is required before execution.",
                blockers=[_issue("site_delete_confirmation_required", "Acknowledge runtime resource deletion.")],
            )
        if delete_dns_resources and not acknowledge_delete_dns_resources:
            raise SEOSiteDeleteError(
                status_code=422,
                reason_code="site_delete_confirmation_required",
                message="DNS, static IP, and managed certificate deletion acknowledgement is required before execution.",
                blockers=[_issue("site_delete_confirmation_required", "Acknowledge DNS/static-IP/certificate deletion.")],
            )

        warnings: list[dict[str, str]] = list(plan.get("warnings") or [])
        blockers: list[dict[str, str]] = []
        if key_warning is not None and key_warning not in warnings:
            warnings.append(key_warning)

        external_resources: list[dict[str, Any]] = []

        runtime_result, runtime_issues = self._execute_runtime_cleanup(
            selected=delete_runtime_resources,
            context=context,
            gcp_deploy_key=gcp_deploy_key,
        )
        external_resources.append(runtime_result)
        blockers.extend(runtime_issues.get("blockers", []))
        warnings.extend(runtime_issues.get("warnings", []))

        managed_certificate_result, certificate_issues = self._execute_managed_certificate_cleanup(
            selected=delete_dns_resources,
            context=context,
            site=site,
            gcp_deploy_key=gcp_deploy_key,
        )
        external_resources.append(managed_certificate_result)
        blockers.extend(certificate_issues.get("blockers", []))
        warnings.extend(certificate_issues.get("warnings", []))

        dns_result, dns_issues = self._execute_dns_cleanup(
            selected=delete_dns_resources,
            context=context,
            gcp_deploy_key=gcp_deploy_key,
        )
        external_resources.append(dns_result)
        blockers.extend(dns_issues.get("blockers", []))
        warnings.extend(dns_issues.get("warnings", []))

        static_ip_result, static_ip_issues = self._execute_static_ip_cleanup(
            selected=delete_dns_resources,
            context=context,
            gcp_deploy_key=gcp_deploy_key,
        )
        external_resources.append(static_ip_result)
        blockers.extend(static_ip_issues.get("blockers", []))
        warnings.extend(static_ip_issues.get("warnings", []))

        github_result, github_issues = self._execute_github_cleanup(
            selected=delete_github_repo,
            context=context,
            business_id=business_id,
            site_id=site_id,
        )
        external_resources.insert(0, github_result)
        blockers.extend(github_issues.get("blockers", []))
        warnings.extend(github_issues.get("warnings", []))

        db_deleted = False
        site_deleted = False
        deleted_external_count = sum(1 for item in external_resources if item.get("status") == "deleted")

        try:
            self._delete_local_site_records(business_id=business_id, site_id=site_id)
            db_deleted = True
            site_deleted = True
        except IntegrityError:
            db_reason_code = (
                "site_delete_db_failed_after_external_cleanup"
                if deleted_external_count > 0
                else "site_delete_foreign_key_blocked"
            )
            db_message = (
                "External cleanup ran, but control-plane database deletion failed. Manual remediation is required."
                if deleted_external_count > 0
                else "Control-plane database deletion was blocked by a foreign-key dependency."
            )
            blockers.append(_issue(db_reason_code, db_message))
        except Exception:
            db_reason_code = (
                "site_delete_db_failed_after_external_cleanup"
                if deleted_external_count > 0
                else "site_delete_transaction_failed"
            )
            db_message = (
                "External cleanup ran, but control-plane database deletion failed. Manual remediation is required."
                if deleted_external_count > 0
                else "Control-plane database deletion failed before commit."
            )
            blockers.append(_issue(db_reason_code, db_message))
        else:
            db_reason_code = "site_delete_completed"
            selected_external_results = [
                item
                for item in external_resources
                if item.get("reason_code") != "external_cleanup_not_selected"
            ]
            partial_external = any(
                item.get("status") in {"failed", "blocked", "skipped", "not_checked"}
                for item in selected_external_results
            )
            if partial_external:
                db_message = "Site deleted from the control-plane database with partial external cleanup."
            elif selected_external_results:
                db_message = "Site deleted from the control-plane database and selected managed resources were cleaned up."
            else:
                db_message = "Site deleted from the control-plane database. External cleanup was not selected."

        if not db_deleted and deleted_external_count > 0 and not any(
            item.get("reason_code") == "site_delete_db_failed_after_external_cleanup" for item in blockers
        ):
            blockers.append(
                _issue(
                    "site_delete_db_failed_after_external_cleanup",
                    "External cleanup completed in part, but control-plane database deletion did not complete.",
                )
            )

        external_cleanup_selected = bool(delete_github_repo or delete_runtime_resources or delete_dns_resources)
        selected_external_results = [
            item
            for item in external_resources
            if item.get("reason_code") != "external_cleanup_not_selected"
        ]
        external_cleanup_partial = any(
            item.get("status") in {"failed", "blocked", "skipped", "not_checked"}
            for item in selected_external_results
        )

        return {
            "reason_code": db_reason_code,
            "message": db_message,
            "site_id": site.id,
            "site_name": site.display_name,
            "domain": site.normalized_domain,
            "db_deleted": db_deleted,
            "site_deleted": site_deleted,
            "external_cleanup_selected": external_cleanup_selected,
            "external_cleanup_partial": external_cleanup_partial,
            "db_dependency_total": plan.get("db_dependency_total", 0),
            "db_dependencies": plan.get("db_dependencies", []),
            "external_resources": external_resources,
            "blockers": blockers,
            "warnings": warnings,
        }

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOSiteNotFoundError("Business not found")

    def _require_site(self, *, business_id: str, site_id: str) -> SEOSite:
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOSiteNotFoundError("SEO site not found")
        return site

    @classmethod
    def _import_model_modules(cls) -> None:
        for module_info in pkgutil.iter_modules(app.models.__path__):
            if module_info.name.startswith("_"):
                continue
            import_module(f"app.models.{module_info.name}")

    @classmethod
    @lru_cache(maxsize=1)
    def _site_owned_models(cls) -> tuple[type[Any], ...]:
        cls._import_model_modules()
        models: list[type[Any]] = []
        for mapper in Base.registry.mappers:
            model = mapper.class_
            table = getattr(model, "__table__", None)
            if table is None or model is SEOSite:
                continue
            has_site_fk = any(
                fk.column.table.name == SEOSite.__tablename__
                for column in table.columns
                for fk in column.foreign_keys
            )
            if has_site_fk:
                models.append(model)
        models.sort(key=lambda item: str(getattr(item, "__tablename__", getattr(item, "__name__", ""))))
        return tuple(models)

    @classmethod
    @lru_cache(maxsize=1)
    def _site_owned_delete_order(cls) -> tuple[type[Any], ...]:
        models = list(cls._site_owned_models())
        table_to_model = {model.__table__.name: model for model in models}
        parent_dependencies: dict[type[Any], set[type[Any]]] = {model: set() for model in models}
        children: dict[type[Any], set[type[Any]]] = {model: set() for model in models}
        for model in models:
            for column in model.__table__.columns:
                for foreign_key in column.foreign_keys:
                    parent = table_to_model.get(foreign_key.column.table.name)
                    if parent is None or parent is model:
                        continue
                    parent_dependencies[model].add(parent)
                    children[parent].add(model)

        in_degree = {model: len(parent_dependencies[model]) for model in models}
        ready = sorted(
            [model for model, dependency_count in in_degree.items() if dependency_count == 0],
            key=lambda item: item.__table__.name,
        )
        parent_first_order: list[type[Any]] = []
        while ready:
            model = ready.pop(0)
            parent_first_order.append(model)
            for child in sorted(children[model], key=lambda item: item.__table__.name):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    ready.append(child)
                    ready.sort(key=lambda item: item.__table__.name)

        if len(parent_first_order) != len(models):
            return tuple(reversed(models))
        return tuple(reversed(parent_first_order))

    def _build_dependency_summary(self, *, business_id: str, site_id: str) -> tuple[list[dict[str, Any]], int]:
        grouped_counts: dict[str, int] = defaultdict(int)
        grouped_models: dict[str, list[str]] = defaultdict(list)
        total = 0
        for model in self._site_owned_models():
            count = self._count_model_rows(model=model, business_id=business_id, site_id=site_id)
            if count <= 0:
                continue
            category = _category_for_model(model)
            grouped_counts[category] += count
            grouped_models[category].append(model.__tablename__)
            total += count
        summaries: list[dict[str, Any]] = []
        for category in sorted(grouped_counts):
            model_names = sorted(grouped_models[category])
            summaries.append(
                {
                    "category": category,
                    "count": grouped_counts[category],
                    "model_count": len(model_names),
                    "model_names": model_names,
                }
            )
        return summaries, total

    def _count_model_rows(self, *, model: type[Any], business_id: str, site_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(model)
            .where(model.business_id == business_id)
            .where(model.site_id == site_id)
        )
        return int(self.session.scalar(stmt) or 0)

    def _build_delete_context(self, *, site: SEOSite, business_id: str) -> _DeleteContext:
        summary = self.seo_migration_service.get_site_cleanup_target_summary(
            business_id=business_id,
            site_id=site.id,
        )
        publish_target = summary.get("publish_target") if isinstance(summary.get("publish_target"), dict) else {}
        deploy_target = summary.get("deploy_target") if isinstance(summary.get("deploy_target"), dict) else {}
        admin_deploy_metadata = (
            summary.get("admin_deploy_metadata")
            if isinstance(summary.get("admin_deploy_metadata"), dict)
            else {}
        )
        repo_owner = _normalize_text(deploy_target.get("repo_owner"), max_length=120) or _normalize_text(
            publish_target.get("repo_owner"),
            max_length=120,
        )
        repo_name = _normalize_text(deploy_target.get("repo_name"), max_length=255) or _normalize_text(
            publish_target.get("repo_name"),
            max_length=255,
        )
        repo_ref = _normalize_text(deploy_target.get("ref"), max_length=120) or _normalize_text(
            publish_target.get("branch"),
            max_length=120,
        ) or "main"
        admin_repo_owner = _normalize_repo_owner(
            getattr(self.seo_migration_service.github_publish_config_service.get(), "repository", None)
            if self.seo_migration_service.github_publish_config_service is not None
            else None
        )

        preview_hostname = _normalize_hostname(deploy_target.get("preview_hostname"))
        static_ip_name = _normalize_text(deploy_target.get("expected_static_ip_name"), max_length=80)
        uses_shared_preview_gateway = bool(deploy_target.get("uses_shared_preview_gateway"))
        managed_certificate_name = _normalize_text(
            deploy_target.get("managed_certificate_name"),
            max_length=63,
        )
        if not managed_certificate_name:
            try:
                managed_certificate_name, _ = derive_site_preview_certificate_name(
                    repo_name=repo_name or "",
                    site_id=site.id,
                )
            except Exception:
                managed_certificate_name = None
        dns_record_name = f"{preview_hostname}." if preview_hostname else None
        return _DeleteContext(
            site_id=site.id,
            repo_owner=repo_owner,
            repo_name=repo_name,
            repo_ref=repo_ref,
            admin_repo_owner=admin_repo_owner,
            kubernetes_namespace=_normalize_text(deploy_target.get("kubernetes_namespace"), max_length=63),
            preview_hostname=preview_hostname,
            static_ip_name=static_ip_name,
            managed_certificate_name=managed_certificate_name,
            dns_record_name=dns_record_name,
            dns_managed_zone=_normalize_text(deploy_target.get("expected_dns_managed_zone"), max_length=120),
            dns_project_id=_normalize_text(deploy_target.get("expected_dns_project_id"), max_length=120),
            dns_ttl=int(deploy_target.get("expected_dns_ttl") or 300),
            managed_gke_config={
                "cluster_name": _normalize_text(
                    admin_deploy_metadata.get("managed_gke_cluster_name"),
                    max_length=120,
                ),
                "cluster_location": _normalize_text(
                    admin_deploy_metadata.get("managed_gke_cluster_location"),
                    max_length=120,
                ),
                "project_id": _normalize_text(
                    admin_deploy_metadata.get("managed_gke_project_id"),
                    max_length=120,
                ),
            },
            namespace_isolation_defaults=(
                admin_deploy_metadata.get("namespace_isolation_defaults")
                if isinstance(admin_deploy_metadata.get("namespace_isolation_defaults"), dict)
                else None
            ),
            uses_shared_preview_gateway=uses_shared_preview_gateway,
        )

    def _build_confirmation_phrase(self, *, site: SEOSite, context: _DeleteContext) -> str:
        repo_fragment = "no-repo"
        if context.repo_owner and context.repo_name:
            repo_fragment = f"{context.repo_owner}/{context.repo_name}"
        elif context.repo_name:
            repo_fragment = context.repo_name
        return f"DELETE {site.display_name} {site.normalized_domain} {repo_fragment}"

    def _load_managed_gcp_deploy_key(self) -> tuple[str | None, dict[str, str] | None]:
        service = self.seo_migration_service.github_publish_config_service
        if service is None:
            return None, None
        try:
            return service.get_managed_gcp_deploy_key_value(), None
        except GitHubPublishConfigSecretError:
            return (
                None,
                _issue(
                    _SITE_DELETE_EXTERNAL_VERIFICATION_LIMITED,
                    "Managed deploy credentials configured in admin settings could not be loaded. Runtime cleanup checks may be limited.",
                ),
            )

    def _plan_github_repo_resource(
        self,
        *,
        context: _DeleteContext,
        business_id: str,
        site_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        if not context.repo_owner or not context.repo_name:
            return (
                _resource(
                    "github_repo",
                    "not_checked",
                    "No generated site repository is configured for this site.",
                    details={
                        "repo_owner": context.repo_owner,
                        "repo_name": context.repo_name,
                        "repo_ref": context.repo_ref,
                    },
                ),
                blockers,
                warnings,
            )
        full_name = _normalize_repo_full_name(f"{context.repo_owner}/{context.repo_name}")
        protected_control_plane_repository = _normalize_repo_full_name(self.protected_control_plane_repository)
        if protected_control_plane_repository is None:
            # Fail closed if the injected guard config is malformed; destructive cleanup must
            # never guess which repo is the protected control-plane source repository.
            summary = (
                "GitHub repository deletion is blocked until the protected control-plane repository setting "
                "is a valid owner/repo value."
            )
            blockers.append(
                _issue(
                    "github_repo_delete_unmanaged_repo_blocked",
                    summary,
                )
            )
            return (
                _resource(
                    "github_repo",
                    "blocked",
                    summary,
                    reason_code="github_repo_delete_unmanaged_repo_blocked",
                    details={
                        "repo_owner": context.repo_owner,
                        "repo_name": context.repo_name,
                        "repo_ref": context.repo_ref,
                    },
                ),
                blockers,
                warnings,
            )
        if full_name == protected_control_plane_repository:
            summary = (
                "This repository is configured as the MBSRN control-plane source repo and cannot be deleted "
                "by site cleanup."
            )
            blockers.append(
                _issue(
                    _GITHUB_REPO_DELETE_PROTECTED_CONTROL_PLANE_REPO_BLOCKED,
                    summary,
                )
            )
            return (
                _resource(
                    "github_repo",
                    "blocked",
                    summary,
                    reason_code=_GITHUB_REPO_DELETE_PROTECTED_CONTROL_PLANE_REPO_BLOCKED,
                    details={
                        "repo_owner": context.repo_owner,
                        "repo_name": context.repo_name,
                        "repo_ref": context.repo_ref,
                    },
                ),
                blockers,
                warnings,
            )
        try:
            preflight = self.seo_migration_service.github_publisher.run_publish_preflight(
                repo_owner=context.repo_owner,
                repo_name=context.repo_name,
                target_ref=context.repo_ref,
                auto_create_enabled=False,
                expected_owner=context.admin_repo_owner,
                expected_business_id=business_id,
                expected_site_id=site_id,
            )
        except SEOMigrationGitHubPublisherError as exc:
            warnings.append(
                _issue(
                    _SITE_DELETE_GIT_REPO_VERIFICATION_LIMITED,
                    "GitHub repository ownership could not be verified during delete planning.",
                )
            )
            return (
                _resource(
                    "github_repo",
                    "not_checked",
                    "GitHub repository ownership could not be verified during delete planning.",
                    details={
                        "repo_owner": context.repo_owner,
                        "repo_name": context.repo_name,
                        "repo_ref": context.repo_ref,
                        "publisher_reason_code": exc.code,
                    },
                ),
                blockers,
                warnings,
            )

        reason_code: str | None = None
        status = "found" if preflight.repo_exists else "not_found"
        summary = "Verified managed GitHub repository candidate for this site."
        if not preflight.repo_exists:
            summary = "No GitHub repository was found for the configured owner/name."
        elif preflight.preflight_blocker_code == "github_repo_adoption_required":
            status = "blocked"
            reason_code = "github_repo_delete_adoption_required"
            summary = "GitHub repository exists, but it is not proven MBSRN-managed for this site."
        elif preflight.preflight_blocker_code:
            status = "blocked"
            reason_code = "github_repo_delete_unmanaged_repo_blocked"
            summary = "GitHub repository exists, but its management marker does not prove this site owns it."

        if status == "blocked" and reason_code is not None:
            blockers.append(_issue(reason_code, summary))

        return (
            _resource(
                "github_repo",
                status,
                summary,
                reason_code=reason_code,
                details={
                    "repo_owner": context.repo_owner,
                    "repo_name": context.repo_name,
                    "repo_ref": context.repo_ref,
                    "repo_exists": preflight.repo_exists,
                    "repo_management_status": preflight.repo_management_status,
                    "repo_management_marker_present": preflight.repo_management_marker_present,
                    "repo_management_marker_valid": preflight.repo_management_marker_valid,
                    "repo_management_marker_matches_site": preflight.repo_management_marker_matches_site,
                    "repo_management_marker_source_ref": preflight.repo_management_marker_source_ref,
                },
            ),
            blockers,
            warnings,
        )

    def _plan_runtime_resource(
        self,
        *,
        context: _DeleteContext,
        gcp_deploy_key: str | None,
    ) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        if not context.kubernetes_namespace:
            return (
                _resource(
                    "gke_runtime",
                    "not_checked",
                    "Managed runtime namespace could not be derived for this site.",
                    details={"kubernetes_namespace": None},
                ),
                blockers,
                warnings,
            )
        try:
            inspection = self._inspect_runtime_resources(
                context=context,
                gcp_deploy_key=gcp_deploy_key,
            )
        except SEOMigrationGitHubPublisherError as exc:
            warnings.append(
                _issue(
                    _SITE_DELETE_RUNTIME_VERIFICATION_LIMITED,
                    "Managed runtime resources could not be verified during delete planning.",
                )
            )
            return (
                _resource(
                    "gke_runtime",
                    "not_checked",
                    "Managed runtime resources could not be verified during delete planning.",
                    details={
                        "kubernetes_namespace": context.kubernetes_namespace,
                        "publisher_reason_code": exc.code,
                    },
                ),
                blockers,
                warnings,
            )

        status = inspection["status"]
        summary = inspection["summary"]
        if status == "blocked":
            blockers.append(
                _issue(
                    "gke_runtime_delete_skipped_unverified_ownership",
                    summary,
                )
            )
        return (
            _resource(
                "gke_runtime",
                status,
                summary,
                details=inspection["details"],
            ),
            blockers,
            warnings,
        )

    def _plan_static_ip_resource(
        self,
        *,
        context: _DeleteContext,
        gcp_deploy_key: str | None,
    ) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        if not context.static_ip_name or not context.managed_gke_config.get("project_id"):
            return (
                _resource(
                    "static_ip",
                    "not_checked",
                    "Managed preview static IP configuration is incomplete for this site.",
                    details={
                        "static_ip_name": context.static_ip_name,
                        "gcp_project_id": context.managed_gke_config.get("project_id"),
                    },
                ),
                blockers,
                warnings,
            )
        if context.uses_shared_preview_gateway:
            warnings.append(
                _issue(
                    _SITE_DELETE_STATIC_IP_SHARED_GATEWAY_NOT_AUTO_DELETED,
                    "Shared preview gateway static IPs are not deleted automatically because they may be reused by other sites.",
                )
            )
        try:
            inspection = self._inspect_static_ip(
                context=context,
                gcp_deploy_key=gcp_deploy_key,
            )
        except SEOMigrationGitHubPublisherError as exc:
            warnings.append(
                _issue(
                    _SITE_DELETE_STATIC_IP_VERIFICATION_LIMITED,
                    "Managed preview static IP could not be verified during delete planning.",
                )
            )
            return (
                _resource(
                    "static_ip",
                    "not_checked",
                    "Managed preview static IP could not be verified during delete planning.",
                    details={
                        "static_ip_name": context.static_ip_name,
                        "publisher_reason_code": exc.code,
                    },
                ),
                blockers,
                warnings,
            )

        return (
            _resource(
                "static_ip",
                inspection["status"],
                inspection["summary"],
                details=inspection["details"],
            ),
            blockers,
            warnings,
        )

    def _plan_dns_resource(
        self,
        *,
        context: _DeleteContext,
        static_ip_resource: dict[str, Any],
        gcp_deploy_key: str | None,
    ) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        expected_ip = _normalize_text((static_ip_resource.get("details") or {}).get("observed_address"), max_length=80)
        if not context.dns_record_name or not context.dns_managed_zone or not context.dns_project_id or not expected_ip:
            return (
                _resource(
                    "dns_record",
                    "not_checked",
                    "Managed preview DNS record could not be fully verified during delete planning.",
                    details={
                        "record_name": context.dns_record_name,
                        "managed_zone": context.dns_managed_zone,
                        "project_id": context.dns_project_id,
                        "expected_ip": expected_ip,
                    },
                ),
                blockers,
                warnings,
            )
        try:
            inspection = self._inspect_dns_record(
                context=context,
                gcp_deploy_key=gcp_deploy_key,
                expected_ip_address=expected_ip,
            )
        except SEOMigrationGitHubPublisherError as exc:
            warnings.append(
                _issue(
                    _SITE_DELETE_DNS_VERIFICATION_LIMITED,
                    "Managed preview DNS record could not be verified during delete planning.",
                )
            )
            return (
                _resource(
                    "dns_record",
                    "not_checked",
                    "Managed preview DNS record could not be verified during delete planning.",
                    details={
                        "record_name": context.dns_record_name,
                        "managed_zone": context.dns_managed_zone,
                        "project_id": context.dns_project_id,
                        "publisher_reason_code": exc.code,
                    },
                ),
                blockers,
                warnings,
            )
        if inspection["status"] == "blocked":
            blockers.append(
                _issue(
                    "site_delete_dependency_blocked",
                    inspection["summary"],
                )
            )
        return (
            _resource(
                "dns_record",
                inspection["status"],
                inspection["summary"],
                details=inspection["details"],
            ),
            blockers,
            warnings,
        )

    def _plan_managed_certificate_resource(
        self,
        *,
        context: _DeleteContext,
        site: SEOSite,
        gcp_deploy_key: str | None,
    ) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        if (
            not context.repo_name
            or not context.preview_hostname
            or not context.kubernetes_namespace
            or not context.managed_certificate_name
        ):
            return (
                _resource(
                    "managed_certificate",
                    "not_checked",
                    "Managed certificate naming or cluster context is incomplete for this site.",
                    details={
                        "managed_certificate_name": context.managed_certificate_name,
                        "preview_hostname": context.preview_hostname,
                        "kubernetes_namespace": context.kubernetes_namespace,
                    },
                ),
                blockers,
                warnings,
            )
        try:
            readiness = self.seo_migration_service.github_publisher.check_managed_certificate_readiness(
                repo_name=context.repo_name,
                site_id=site.id,
                preview_hostname=context.preview_hostname,
                kubernetes_namespace=context.kubernetes_namespace,
                managed_gke_config=context.managed_gke_config,
                gcp_deploy_key=gcp_deploy_key,
                expected_managed_certificate_name=context.managed_certificate_name,
            )
        except SEOMigrationGitHubPublisherError as exc:
            warnings.append(
                _issue(
                    _SITE_DELETE_MANAGED_CERTIFICATE_VERIFICATION_LIMITED,
                    "Managed certificate ownership could not be verified during delete planning.",
                )
            )
            return (
                _resource(
                    "managed_certificate",
                    "not_checked",
                    "Managed certificate ownership could not be verified during delete planning.",
                    details={
                        "managed_certificate_name": context.managed_certificate_name,
                        "publisher_reason_code": exc.code,
                    },
                ),
                blockers,
                warnings,
            )
        if readiness is None:
            return (
                _resource(
                    "managed_certificate",
                    "not_checked",
                    "Managed certificate readiness could not be evaluated for this site.",
                    details={
                        "managed_certificate_name": context.managed_certificate_name,
                    },
                ),
                blockers,
                warnings,
            )
        status = "found" if readiness.managed_certificate_exists else "not_found"
        summary = "Verified managed certificate candidate for this site."
        if readiness.managed_certificate_exists and readiness.certificate_domain_matches_expected is False:
            status = "blocked"
            summary = "Managed certificate exists, but its domain binding does not prove this site owns it."
            blockers.append(_issue("site_delete_dependency_blocked", summary))
        elif not readiness.managed_certificate_exists:
            summary = "No managed certificate was found for the expected namespace/name."
        return (
            _resource(
                "managed_certificate",
                status,
                summary,
                details={
                    "managed_certificate_name": readiness.managed_certificate_name,
                    "preview_hostname": readiness.preview_hostname,
                    "kubernetes_namespace": readiness.kubernetes_namespace,
                    "managed_certificate_exists": readiness.managed_certificate_exists,
                    "certificate_domain_matches_expected": readiness.certificate_domain_matches_expected,
                    "observed_managed_certificate_domains": list(readiness.observed_managed_certificate_domains),
                    "observed_managed_certificate_status": readiness.observed_managed_certificate_status,
                    "observed_managed_certificate_domain_status": readiness.observed_managed_certificate_domain_status,
                },
            ),
            blockers,
            warnings,
        )

    def _execute_runtime_cleanup(
        self,
        *,
        selected: bool,
        context: _DeleteContext,
        gcp_deploy_key: str | None,
    ) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
        issues = {"blockers": [], "warnings": []}
        if not selected:
            return (
                _resource(
                    "gke_runtime",
                    "skipped",
                    "Managed runtime cleanup was not selected.",
                    reason_code="external_cleanup_not_selected",
                    details={"kubernetes_namespace": context.kubernetes_namespace},
                ),
                issues,
            )
        try:
            inspection = self._inspect_runtime_resources(
                context=context,
                gcp_deploy_key=gcp_deploy_key,
            )
        except SEOMigrationGitHubPublisherError:
            issues["warnings"].append(
                _issue(
                    "gke_runtime_delete_skipped_unverified_ownership",
                    "Managed runtime cleanup was skipped because ownership could not be verified.",
                )
            )
            return (
                _resource(
                    "gke_runtime",
                    "skipped",
                    "Managed runtime cleanup was skipped because ownership could not be verified.",
                    reason_code="gke_runtime_delete_skipped_unverified_ownership",
                    details={"kubernetes_namespace": context.kubernetes_namespace},
                ),
                issues,
            )
        if inspection["status"] in {"not_checked", "blocked"}:
            issues["warnings"].append(
                _issue(
                    "gke_runtime_delete_skipped_unverified_ownership",
                    "Managed runtime cleanup was skipped because ownership verification did not pass.",
                )
            )
            return (
                _resource(
                    "gke_runtime",
                    "skipped",
                    "Managed runtime cleanup was skipped because ownership verification did not pass.",
                    reason_code="gke_runtime_delete_skipped_unverified_ownership",
                    details=inspection["details"],
                ),
                issues,
            )
        if inspection["status"] == "not_found":
            return (
                _resource(
                    "gke_runtime",
                    "not_found",
                    "No verified managed runtime resources were found for this site.",
                    details=inspection["details"],
                ),
                issues,
            )

        try:
            cluster_access = self._resolve_cluster_access(
                managed_gke_config=context.managed_gke_config,
                gcp_deploy_key=gcp_deploy_key,
                stage="site_delete_runtime",
            )
        except SEOMigrationGitHubPublisherError:
            issues["warnings"].append(
                _issue(
                    "gke_runtime_delete_skipped_unverified_ownership",
                    "Managed runtime cleanup was skipped because cluster ownership could not be verified.",
                )
            )
            return (
                _resource(
                    "gke_runtime",
                    "skipped",
                    "Managed runtime cleanup was skipped because cluster ownership could not be verified.",
                    reason_code="gke_runtime_delete_skipped_unverified_ownership",
                    details=inspection["details"],
                ),
                issues,
            )
        resource_paths = self._runtime_resource_paths(context=context)
        deleted_resources: list[str] = []
        failed_resources: list[str] = []
        for resource_name, resource_path in resource_paths.items():
            payload = _request_kubernetes_json(
                method="GET",
                endpoint=cluster_access.cluster_endpoint,
                path=resource_path,
                access_token=cluster_access.access_token,
                ssl_context=cluster_access.ssl_context,
                timeout_seconds=cluster_access.timeout_seconds,
                allow_404=True,
                error_stage="site_delete_runtime",
            )
            if not isinstance(payload, dict):
                continue
            if resource_name == "image_pull_secret":
                namespace_payload = _request_kubernetes_json(
                    method="GET",
                    endpoint=cluster_access.cluster_endpoint,
                    path=f"/api/v1/namespaces/{urllib.parse.quote(context.kubernetes_namespace or '', safe='')}",
                    access_token=cluster_access.access_token,
                    ssl_context=cluster_access.ssl_context,
                    timeout_seconds=cluster_access.timeout_seconds,
                    allow_404=True,
                    error_stage="site_delete_runtime",
                )
                if not self._namespace_owned(namespace_payload=namespace_payload, context=context):
                    failed_resources.append(resource_name)
                    continue
            elif not self._resource_owned(payload=payload, context=context):
                failed_resources.append(resource_name)
                continue
            try:
                _request_kubernetes_json(
                    method="DELETE",
                    endpoint=cluster_access.cluster_endpoint,
                    path=resource_path,
                    access_token=cluster_access.access_token,
                    ssl_context=cluster_access.ssl_context,
                    timeout_seconds=cluster_access.timeout_seconds,
                    expected_statuses=(200, 202),
                    allow_404=True,
                    error_stage="site_delete_runtime",
                )
                deleted_resources.append(resource_name)
            except SEOMigrationGitHubPublisherError:
                failed_resources.append(resource_name)

        if failed_resources:
            issues["warnings"].append(
                _issue(
                    "gke_runtime_delete_failed",
                    "One or more runtime resources could not be deleted safely.",
                )
            )
            return (
                _resource(
                    "gke_runtime",
                    "failed",
                    "One or more runtime resources could not be deleted safely.",
                    reason_code="gke_runtime_delete_failed",
                    details={
                        "kubernetes_namespace": context.kubernetes_namespace,
                        "deleted_resources": deleted_resources,
                        "failed_resources": failed_resources,
                    },
                ),
                issues,
            )
        return (
            _resource(
                "gke_runtime",
                "deleted" if deleted_resources else "not_found",
                (
                    f"Deleted {len(deleted_resources)} verified managed runtime resources."
                    if deleted_resources
                    else "No verified managed runtime resources were found for this site."
                ),
                reason_code="gke_runtime_deleted" if deleted_resources else None,
                details={
                    "kubernetes_namespace": context.kubernetes_namespace,
                    "deleted_resources": deleted_resources,
                    "failed_resources": failed_resources,
                },
            ),
            issues,
        )

    def _execute_managed_certificate_cleanup(
        self,
        *,
        selected: bool,
        context: _DeleteContext,
        site: SEOSite,
        gcp_deploy_key: str | None,
    ) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
        issues = {"blockers": [], "warnings": []}
        if not selected:
            return (
                _resource(
                    "managed_certificate",
                    "skipped",
                    "Managed certificate cleanup was not selected.",
                    reason_code="external_cleanup_not_selected",
                    details={"managed_certificate_name": context.managed_certificate_name},
                ),
                issues,
            )
        if not context.managed_certificate_name or not context.kubernetes_namespace:
            issues["warnings"].append(
                _issue(
                    "managed_certificate_delete_failed",
                    "Managed certificate cleanup is missing namespace or certificate naming context.",
                )
            )
            return (
                _resource(
                    "managed_certificate",
                    "blocked",
                    "Managed certificate cleanup is missing namespace or certificate naming context.",
                    details={
                        "managed_certificate_name": context.managed_certificate_name,
                        "kubernetes_namespace": context.kubernetes_namespace,
                    },
                ),
                issues,
            )
        try:
            cluster_access = self._resolve_cluster_access(
                managed_gke_config=context.managed_gke_config,
                gcp_deploy_key=gcp_deploy_key,
                stage="site_delete_certificate",
            )
        except SEOMigrationGitHubPublisherError:
            issues["warnings"].append(
                _issue(
                    "managed_certificate_delete_failed",
                    "Managed certificate cleanup was skipped because cluster ownership could not be verified.",
                )
            )
            return (
                _resource(
                    "managed_certificate",
                    "blocked",
                    "Managed certificate cleanup was skipped because cluster ownership could not be verified.",
                    details={
                        "managed_certificate_name": context.managed_certificate_name,
                        "kubernetes_namespace": context.kubernetes_namespace,
                    },
                ),
                issues,
            )
        resource_path = (
            "/apis/networking.gke.io/v1/namespaces/"
            f"{urllib.parse.quote(context.kubernetes_namespace, safe='')}/managedcertificates/"
            f"{urllib.parse.quote(context.managed_certificate_name, safe='')}"
        )
        payload = _request_kubernetes_json(
            method="GET",
            endpoint=cluster_access.cluster_endpoint,
            path=resource_path,
            access_token=cluster_access.access_token,
            ssl_context=cluster_access.ssl_context,
            timeout_seconds=cluster_access.timeout_seconds,
            allow_404=True,
            error_stage="site_delete_certificate",
        )
        if not isinstance(payload, dict):
            return (
                _resource(
                    "managed_certificate",
                    "not_found",
                    "No managed certificate was found for the expected namespace/name.",
                    details={
                        "managed_certificate_name": context.managed_certificate_name,
                        "kubernetes_namespace": context.kubernetes_namespace,
                    },
                ),
                issues,
            )
        if not self._resource_owned(payload=payload, context=context):
            issues["warnings"].append(
                _issue(
                    "managed_certificate_delete_failed",
                    "Managed certificate cleanup was skipped because ownership verification did not pass.",
                )
            )
            return (
                _resource(
                    "managed_certificate",
                    "blocked",
                    "Managed certificate cleanup was skipped because ownership verification did not pass.",
                    details={
                        "managed_certificate_name": context.managed_certificate_name,
                        "kubernetes_namespace": context.kubernetes_namespace,
                    },
                ),
                issues,
            )
        try:
            _request_kubernetes_json(
                method="DELETE",
                endpoint=cluster_access.cluster_endpoint,
                path=resource_path,
                access_token=cluster_access.access_token,
                ssl_context=cluster_access.ssl_context,
                timeout_seconds=cluster_access.timeout_seconds,
                expected_statuses=(200, 202),
                allow_404=True,
                error_stage="site_delete_certificate",
            )
        except SEOMigrationGitHubPublisherError:
            issues["warnings"].append(
                _issue(
                    "managed_certificate_delete_failed",
                    "Managed certificate deletion request failed.",
                )
            )
            return (
                _resource(
                    "managed_certificate",
                    "failed",
                    "Managed certificate deletion request failed.",
                    reason_code="managed_certificate_delete_failed",
                    details={
                        "managed_certificate_name": context.managed_certificate_name,
                        "kubernetes_namespace": context.kubernetes_namespace,
                    },
                ),
                issues,
            )
        return (
            _resource(
                "managed_certificate",
                "deleted",
                "Deleted the verified managed certificate resource for this site.",
                reason_code="managed_certificate_deleted",
                details={
                    "managed_certificate_name": context.managed_certificate_name,
                    "kubernetes_namespace": context.kubernetes_namespace,
                },
            ),
            issues,
        )

    def _execute_dns_cleanup(
        self,
        *,
        selected: bool,
        context: _DeleteContext,
        gcp_deploy_key: str | None,
    ) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
        issues = {"blockers": [], "warnings": []}
        if not selected:
            return (
                _resource(
                    "dns_record",
                    "skipped",
                    "Managed DNS cleanup was not selected.",
                    reason_code="external_cleanup_not_selected",
                    details={"record_name": context.dns_record_name},
                ),
                issues,
            )
        try:
            static_ip_inspection = self._inspect_static_ip(
                context=context,
                gcp_deploy_key=gcp_deploy_key,
            )
        except SEOMigrationGitHubPublisherError:
            issues["warnings"].append(
                _issue(
                    "dns_record_delete_failed",
                    "Managed DNS cleanup was skipped because the static IP could not be verified.",
                )
            )
            return (
                _resource(
                    "dns_record",
                    "blocked",
                    "Managed DNS cleanup was skipped because the static IP could not be verified.",
                    details={
                        "record_name": context.dns_record_name,
                        "managed_zone": context.dns_managed_zone,
                        "project_id": context.dns_project_id,
                    },
                ),
                issues,
            )
        expected_ip = _normalize_text(static_ip_inspection["details"].get("observed_address"), max_length=80)
        if not expected_ip:
            issues["warnings"].append(
                _issue(
                    "dns_record_delete_failed",
                    "Managed DNS cleanup was skipped because the expected static IP address could not be verified.",
                )
            )
            return (
                _resource(
                    "dns_record",
                    "blocked",
                    "Managed DNS cleanup was skipped because the expected static IP address could not be verified.",
                    details=static_ip_inspection["details"],
                ),
                issues,
            )
        try:
            inspection = self._inspect_dns_record(
                context=context,
                gcp_deploy_key=gcp_deploy_key,
                expected_ip_address=expected_ip,
            )
        except SEOMigrationGitHubPublisherError:
            issues["warnings"].append(
                _issue(
                    "dns_record_delete_failed",
                    "Managed DNS cleanup was skipped because DNS ownership could not be verified.",
                )
            )
            return (
                _resource(
                    "dns_record",
                    "blocked",
                    "Managed DNS cleanup was skipped because DNS ownership could not be verified.",
                    details={
                        "record_name": context.dns_record_name,
                        "managed_zone": context.dns_managed_zone,
                        "project_id": context.dns_project_id,
                        "expected_ip": expected_ip,
                    },
                ),
                issues,
            )
        if inspection["status"] == "not_found":
            return (
                _resource(
                    "dns_record",
                    "not_found",
                    "No managed DNS A record was found for the expected hostname.",
                    details=inspection["details"],
                ),
                issues,
            )
        if inspection["status"] != "found":
            issues["warnings"].append(
                _issue(
                    "dns_record_delete_failed",
                    "Managed DNS cleanup was skipped because record ownership or value verification did not pass.",
                )
            )
            return (
                _resource(
                    "dns_record",
                    "blocked",
                    "Managed DNS cleanup was skipped because record ownership or value verification did not pass.",
                    details=inspection["details"],
                ),
                issues,
            )
        try:
            access_token, timeout_seconds = self._resolve_google_access_token(
                gcp_deploy_key=gcp_deploy_key,
                stage="site_delete_dns",
            )
        except SEOMigrationGitHubPublisherError:
            issues["warnings"].append(
                _issue(
                    "dns_record_delete_failed",
                    "Managed DNS deletion credentials could not be resolved.",
                )
            )
            return (
                _resource(
                    "dns_record",
                    "failed",
                    "Managed DNS deletion credentials could not be resolved.",
                    reason_code="dns_record_delete_failed",
                    details=inspection["details"],
                ),
                issues,
            )
        encoded_project = urllib.parse.quote(context.dns_project_id or "", safe="")
        encoded_zone = urllib.parse.quote(context.dns_managed_zone or "", safe="")
        changes_url = (
            "https://dns.googleapis.com/dns/v1/projects/"
            f"{encoded_project}/managedZones/{encoded_zone}/changes"
        )
        rrdata_values = list((inspection["details"].get("observed_ips") or []))
        ttl_value = int(inspection["details"].get("observed_ttl") or context.dns_ttl or 300)
        try:
            _request_google_json(
                method="POST",
                url=changes_url,
                payload={
                    "deletions": [
                        {
                            "name": context.dns_record_name,
                            "type": "A",
                            "ttl": ttl_value,
                            "rrdatas": rrdata_values,
                        }
                    ]
                },
                access_token=access_token,
                timeout_seconds=timeout_seconds,
                expected_statuses=(200, 201),
                error_stage="site_delete_dns",
                code_on_failure="dns_record_delete_failed",
                safe_message_on_failure="Managed DNS deletion request failed.",
                safe_message_on_timeout="Managed DNS deletion request timed out.",
            )
        except SEOMigrationGitHubPublisherError:
            issues["warnings"].append(
                _issue(
                    "dns_record_delete_failed",
                    "Managed DNS deletion request failed.",
                )
            )
            return (
                _resource(
                    "dns_record",
                    "failed",
                    "Managed DNS deletion request failed.",
                    reason_code="dns_record_delete_failed",
                    details=inspection["details"],
                ),
                issues,
            )
        return (
            _resource(
                "dns_record",
                "deleted",
                "Deleted the verified managed preview DNS A record for this site.",
                reason_code="dns_record_deleted",
                details=inspection["details"],
            ),
            issues,
        )

    def _execute_static_ip_cleanup(
        self,
        *,
        selected: bool,
        context: _DeleteContext,
        gcp_deploy_key: str | None,
    ) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
        issues = {"blockers": [], "warnings": []}
        if not selected:
            return (
                _resource(
                    "static_ip",
                    "skipped",
                    "Managed static IP cleanup was not selected.",
                    reason_code="external_cleanup_not_selected",
                    details={"static_ip_name": context.static_ip_name},
                ),
                issues,
            )
        if context.uses_shared_preview_gateway:
            issues["warnings"].append(
                _issue(
                    "static_ip_delete_skipped_in_use",
                    "Shared preview gateway static IPs are not deleted automatically.",
                )
            )
            return (
                _resource(
                    "static_ip",
                    "skipped",
                    "Shared preview gateway static IPs are not deleted automatically.",
                    reason_code="static_ip_delete_skipped_in_use",
                    details={"static_ip_name": context.static_ip_name},
                ),
                issues,
            )
        try:
            inspection = self._inspect_static_ip(context=context, gcp_deploy_key=gcp_deploy_key)
        except SEOMigrationGitHubPublisherError:
            issues["warnings"].append(
                _issue(
                    "static_ip_delete_failed",
                    "Managed preview static IP could not be verified for deletion.",
                )
            )
            return (
                _resource(
                    "static_ip",
                    "failed",
                    "Managed preview static IP could not be verified for deletion.",
                    reason_code="static_ip_delete_failed",
                    details={"static_ip_name": context.static_ip_name},
                ),
                issues,
            )
        if inspection["status"] == "not_found":
            return (
                _resource(
                    "static_ip",
                    "not_found",
                    "No managed preview static IP was found for the expected project/name.",
                    details=inspection["details"],
                ),
                issues,
            )
        observed_users = list(inspection["details"].get("observed_users") or [])
        if observed_users:
            issues["warnings"].append(
                _issue(
                    "static_ip_delete_skipped_in_use",
                    "Managed preview static IP deletion was skipped because the address is still in use.",
                )
            )
            return (
                _resource(
                    "static_ip",
                    "skipped",
                    "Managed preview static IP deletion was skipped because the address is still in use.",
                    reason_code="static_ip_delete_skipped_in_use",
                    details=inspection["details"],
                ),
                issues,
            )
        try:
            access_token, timeout_seconds = self._resolve_google_access_token(
                gcp_deploy_key=gcp_deploy_key,
                stage="site_delete_static_ip",
            )
        except SEOMigrationGitHubPublisherError:
            issues["warnings"].append(
                _issue(
                    "static_ip_delete_failed",
                    "Managed preview static IP deletion credentials could not be resolved.",
                )
            )
            return (
                _resource(
                    "static_ip",
                    "failed",
                    "Managed preview static IP deletion credentials could not be resolved.",
                    reason_code="static_ip_delete_failed",
                    details=inspection["details"],
                ),
                issues,
            )
        encoded_project = urllib.parse.quote(context.managed_gke_config.get("project_id") or "", safe="")
        encoded_name = urllib.parse.quote(context.static_ip_name or "", safe="")
        address_url = (
            "https://compute.googleapis.com/compute/v1/projects/"
            f"{encoded_project}/global/addresses/{encoded_name}"
        )
        try:
            _request_google_json(
                method="DELETE",
                url=address_url,
                access_token=access_token,
                timeout_seconds=timeout_seconds,
                expected_statuses=(200, 202, 204),
                allow_404=True,
                error_stage="site_delete_static_ip",
                code_on_failure="static_ip_delete_failed",
                safe_message_on_failure="Managed static IP deletion request failed.",
                safe_message_on_timeout="Managed static IP deletion request timed out.",
            )
        except SEOMigrationGitHubPublisherError:
            issues["warnings"].append(
                _issue(
                    "static_ip_delete_failed",
                    "Managed preview static IP deletion request failed.",
                )
            )
            return (
                _resource(
                    "static_ip",
                    "failed",
                    "Managed preview static IP deletion request failed.",
                    reason_code="static_ip_delete_failed",
                    details=inspection["details"],
                ),
                issues,
            )
        return (
            _resource(
                "static_ip",
                "deleted",
                "Deleted the verified managed preview static IP reservation for this site.",
                reason_code="static_ip_deleted",
                details=inspection["details"],
            ),
            issues,
        )

    def _execute_github_cleanup(
        self,
        *,
        selected: bool,
        context: _DeleteContext,
        business_id: str,
        site_id: str,
    ) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
        issues = {"blockers": [], "warnings": []}
        if not selected:
            return (
                _resource(
                    "github_repo",
                    "skipped",
                    "GitHub repository cleanup was not selected.",
                    reason_code="external_cleanup_not_selected",
                    details={
                        "repo_owner": context.repo_owner,
                        "repo_name": context.repo_name,
                        "repo_ref": context.repo_ref,
                    },
                ),
                issues,
            )
        planned_resource, planned_blockers, planned_warnings = self._plan_github_repo_resource(
            context=context,
            business_id=business_id,
            site_id=site_id,
        )
        issues["blockers"].extend(planned_blockers)
        issues["warnings"].extend(planned_warnings)
        if planned_resource.get("status") == "not_found":
            return (
                _resource(
                    "github_repo",
                    "not_found",
                    "No GitHub repository was found for the configured owner/name.",
                    details=planned_resource.get("details") or {},
                ),
                issues,
            )
        if planned_resource.get("status") != "found":
            return (
                _resource(
                    "github_repo",
                    "blocked",
                    str(planned_resource.get("summary") or "GitHub repository cleanup was blocked."),
                    reason_code=str(planned_resource.get("reason_code") or "") or None,
                    details=planned_resource.get("details") or {},
                ),
                issues,
            )
        publisher = self.seo_migration_service.github_publisher
        try:
            publisher.delete_repository(
                repo_owner=context.repo_owner or "",
                repo_name=context.repo_name or "",
            )
        except SEOMigrationGitHubPublisherError:
            issues["warnings"].append(
                _issue(
                    "github_repo_delete_failed",
                    "GitHub repository deletion request failed.",
                )
            )
            return (
                _resource(
                    "github_repo",
                    "failed",
                    "GitHub repository deletion request failed.",
                    reason_code="github_repo_delete_failed",
                    details=planned_resource.get("details") or {},
                ),
                issues,
            )
        return (
            _resource(
                "github_repo",
                "deleted",
                "Deleted the verified managed GitHub repository for this site.",
                reason_code="github_repo_deleted",
                details=planned_resource.get("details") or {},
            ),
            issues,
        )

    def _delete_local_site_records(self, *, business_id: str, site_id: str) -> None:
        for model in self._site_owned_delete_order():
            self.session.execute(
                delete(model).where(model.business_id == business_id).where(model.site_id == site_id)
            )
        deleted_site = self.session.execute(
            delete(SEOSite).where(SEOSite.business_id == business_id).where(SEOSite.id == site_id)
        )
        if int(deleted_site.rowcount or 0) != 1:
            self.session.rollback()
            raise IntegrityError("seo_site_delete_rowcount_mismatch", None, None)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def _resolve_google_access_token(self, *, gcp_deploy_key: str | None, stage: str) -> tuple[str, int]:
        publisher = self.seo_migration_service.github_publisher
        timeout_seconds = max(1, int(getattr(publisher, "timeout_seconds", 15) or 15))
        impersonated_service_account_email = _normalize_text(
            getattr(publisher, "managed_deploy_service_account_email", None),
            max_length=200,
        )
        validated_impersonated_email = None
        if impersonated_service_account_email:
            validated_impersonated_email = _validate_managed_deploy_impersonation_service_account_email(
                impersonated_service_account_email,
                stage=stage,
            )
        access_token = _resolve_google_access_token_for_managed_deploy_operations(
            credentials_json=gcp_deploy_key,
            impersonated_service_account_email=validated_impersonated_email,
            missing_code="site_delete_dependency_blocked",
            missing_safe_message="Managed deploy runtime credential is unavailable for delete verification.",
            invalid_code="site_delete_dependency_blocked",
            invalid_safe_message="Managed deploy runtime credential is invalid for delete verification.",
            integration_code="site_delete_dependency_blocked",
            integration_safe_message="Google auth runtime dependency is unavailable for delete verification.",
            stage=stage,
        )
        return access_token, timeout_seconds

    def _resolve_cluster_access(
        self,
        *,
        managed_gke_config: dict[str, str | None],
        gcp_deploy_key: str | None,
        stage: str,
    ) -> _ClusterAccess:
        cluster_name = _normalize_text(managed_gke_config.get("cluster_name"), max_length=120)
        cluster_location = _normalize_text(managed_gke_config.get("cluster_location"), max_length=120)
        project_id = _normalize_text(managed_gke_config.get("project_id"), max_length=120)
        if not cluster_name or not cluster_location or not project_id:
            raise SEOMigrationGitHubPublisherError(
                code="site_delete_dependency_blocked",
                safe_message="Managed GKE cluster configuration is incomplete for runtime cleanup.",
                stage=stage,
            )
        access_token, timeout_seconds = self._resolve_google_access_token(
            gcp_deploy_key=gcp_deploy_key,
            stage=stage,
        )
        cluster_payload = _request_google_json(
            method="GET",
            url=(
                "https://container.googleapis.com/v1/projects/"
                f"{urllib.parse.quote(project_id, safe='')}/locations/{urllib.parse.quote(cluster_location, safe='')}"
                f"/clusters/{urllib.parse.quote(cluster_name, safe='')}"
            ),
            access_token=access_token,
            timeout_seconds=timeout_seconds,
            error_stage=stage,
            code_on_failure="site_delete_dependency_blocked",
            safe_message_on_failure="Managed GKE cluster metadata could not be resolved for delete verification.",
            safe_message_on_timeout="Managed GKE cluster metadata lookup timed out during delete verification.",
        )
        if not isinstance(cluster_payload, dict):
            raise SEOMigrationGitHubPublisherError(
                code="site_delete_dependency_blocked",
                safe_message="Managed GKE cluster metadata could not be resolved for delete verification.",
                stage=stage,
            )
        cluster_endpoint = _normalize_text(cluster_payload.get("endpoint"), max_length=255)
        master_auth = cluster_payload.get("masterAuth")
        cluster_ca_certificate = (
            _normalize_text(master_auth.get("clusterCaCertificate"), max_length=100000)
            if isinstance(master_auth, dict)
            else None
        )
        if not cluster_endpoint or not cluster_ca_certificate:
            raise SEOMigrationGitHubPublisherError(
                code="site_delete_dependency_blocked",
                safe_message="Managed GKE cluster endpoint metadata is incomplete for delete verification.",
                stage=stage,
            )
        decoded_cluster_ca = base64.b64decode(cluster_ca_certificate.encode("ascii")).decode("utf-8", errors="ignore")
        return _ClusterAccess(
            cluster_endpoint=cluster_endpoint,
            ssl_context=ssl.create_default_context(cadata=decoded_cluster_ca),
            access_token=access_token,
            timeout_seconds=timeout_seconds,
        )

    def _runtime_resource_paths(self, *, context: _DeleteContext) -> dict[str, str]:
        namespace = urllib.parse.quote(context.kubernetes_namespace or "", safe="")
        frontend_config_name = None
        backend_config_name = None
        if context.repo_name:
            try:
                frontend_config_name, _ = derive_site_preview_frontend_config_name(
                    repo_name=context.repo_name,
                    site_id=context.site_id,
                )
                backend_config_name, _ = derive_site_preview_backend_config_name(
                    repo_name=context.repo_name,
                    site_id=context.site_id,
                )
            except Exception:
                frontend_config_name = None
                backend_config_name = None
        paths = {
            "ingress": f"/apis/networking.k8s.io/v1/namespaces/{namespace}/ingresses/site-web",
            "service": f"/api/v1/namespaces/{namespace}/services/site-web",
            "deployment": f"/apis/apps/v1/namespaces/{namespace}/deployments/site-web",
            "resource_quota": f"/api/v1/namespaces/{namespace}/resourcequotas/{_MBSRN_RESOURCE_QUOTA_NAME}",
            "limit_range": f"/api/v1/namespaces/{namespace}/limitranges/{_MBSRN_LIMIT_RANGE_NAME}",
            "network_policy_default": (
                f"/apis/networking.k8s.io/v1/namespaces/{namespace}/networkpolicies/"
                f"{_MBSRN_NETWORK_POLICY_NAMES[0]}"
            ),
            "network_policy_allow": (
                f"/apis/networking.k8s.io/v1/namespaces/{namespace}/networkpolicies/"
                f"{_MBSRN_NETWORK_POLICY_NAMES[1]}"
            ),
            "image_pull_secret": (
                f"/api/v1/namespaces/{namespace}/secrets/{urllib.parse.quote(_MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME, safe='')}"
            ),
        }
        if frontend_config_name:
            paths["frontend_config"] = (
                f"/apis/networking.gke.io/v1beta1/namespaces/{namespace}/frontendconfigs/"
                f"{urllib.parse.quote(frontend_config_name, safe='')}"
            )
        if backend_config_name:
            paths["backend_config"] = (
                f"/apis/cloud.google.com/v1/namespaces/{namespace}/backendconfigs/"
                f"{urllib.parse.quote(backend_config_name, safe='')}"
            )
        return paths

    def _inspect_runtime_resources(
        self,
        *,
        context: _DeleteContext,
        gcp_deploy_key: str | None,
    ) -> dict[str, Any]:
        cluster_access = self._resolve_cluster_access(
            managed_gke_config=context.managed_gke_config,
            gcp_deploy_key=gcp_deploy_key,
            stage="site_delete_runtime_plan",
        )
        namespace_path = f"/api/v1/namespaces/{urllib.parse.quote(context.kubernetes_namespace or '', safe='')}"
        namespace_payload = _request_kubernetes_json(
            method="GET",
            endpoint=cluster_access.cluster_endpoint,
            path=namespace_path,
            access_token=cluster_access.access_token,
            ssl_context=cluster_access.ssl_context,
            timeout_seconds=cluster_access.timeout_seconds,
            allow_404=True,
            error_stage="site_delete_runtime_plan",
        )
        namespace_owned = self._namespace_owned(namespace_payload=namespace_payload, context=context)
        observed_resources: list[dict[str, str]] = []
        verified_owned_count = 0
        mismatched_resources: list[str] = []
        found_any = False
        for resource_name, resource_path in self._runtime_resource_paths(context=context).items():
            payload = _request_kubernetes_json(
                method="GET",
                endpoint=cluster_access.cluster_endpoint,
                path=resource_path,
                access_token=cluster_access.access_token,
                ssl_context=cluster_access.ssl_context,
                timeout_seconds=cluster_access.timeout_seconds,
                allow_404=True,
                error_stage="site_delete_runtime_plan",
            )
            if not isinstance(payload, dict):
                observed_resources.append({"resource": resource_name, "status": "not_found"})
                continue
            found_any = True
            if resource_name == "image_pull_secret":
                owned = namespace_owned
            else:
                owned = self._resource_owned(payload=payload, context=context)
            if owned:
                verified_owned_count += 1
                observed_resources.append({"resource": resource_name, "status": "verified"})
            else:
                mismatched_resources.append(resource_name)
                observed_resources.append({"resource": resource_name, "status": "unverified"})

        if mismatched_resources:
            return {
                "status": "blocked",
                "summary": "Runtime resources were found, but one or more resources did not pass ownership verification.",
                "details": {
                    "kubernetes_namespace": context.kubernetes_namespace,
                    "namespace_owned": namespace_owned,
                    "verified_owned_count": verified_owned_count,
                    "observed_resources": observed_resources,
                    "mismatched_resources": mismatched_resources,
                },
            }
        if found_any:
            return {
                "status": "found",
                "summary": "Verified managed runtime resources were found for this site.",
                "details": {
                    "kubernetes_namespace": context.kubernetes_namespace,
                    "namespace_owned": namespace_owned,
                    "verified_owned_count": verified_owned_count,
                    "observed_resources": observed_resources,
                    "mismatched_resources": mismatched_resources,
                },
            }
        return {
            "status": "not_found",
            "summary": "No verified managed runtime resources were found for this site.",
            "details": {
                "kubernetes_namespace": context.kubernetes_namespace,
                "namespace_owned": namespace_owned,
                "verified_owned_count": verified_owned_count,
                "observed_resources": observed_resources,
                "mismatched_resources": mismatched_resources,
            },
        }

    def _inspect_static_ip(self, *, context: _DeleteContext, gcp_deploy_key: str | None) -> dict[str, Any]:
        access_token, timeout_seconds = self._resolve_google_access_token(
            gcp_deploy_key=gcp_deploy_key,
            stage="site_delete_static_ip_plan",
        )
        project_id = context.managed_gke_config.get("project_id") or ""
        address_url = (
            "https://compute.googleapis.com/compute/v1/projects/"
            f"{urllib.parse.quote(project_id, safe='')}/global/addresses/"
            f"{urllib.parse.quote(context.static_ip_name or '', safe='')}"
        )
        payload = _request_google_json(
            method="GET",
            url=address_url,
            access_token=access_token,
            timeout_seconds=timeout_seconds,
            allow_404=True,
            error_stage="site_delete_static_ip_plan",
            code_on_failure="site_delete_dependency_blocked",
            safe_message_on_failure="Managed static IP lookup failed during delete planning.",
            safe_message_on_timeout="Managed static IP lookup timed out during delete planning.",
        )
        if not isinstance(payload, dict):
            return {
                "status": "not_found",
                "summary": "No managed preview static IP was found for the expected project/name.",
                "details": {
                    "static_ip_name": context.static_ip_name,
                    "gcp_project_id": project_id,
                    "observed_address": None,
                    "observed_users": [],
                },
            }
        observed_users = []
        raw_users = payload.get("users")
        if isinstance(raw_users, list):
            for item in raw_users:
                candidate = _normalize_text(item, max_length=500)
                if candidate:
                    observed_users.append(candidate)
        return {
            "status": "found",
            "summary": "Managed preview static IP candidate was found for this site.",
            "details": {
                "static_ip_name": context.static_ip_name,
                "gcp_project_id": project_id,
                "observed_address": _normalize_text(payload.get("address"), max_length=80),
                "observed_users": observed_users,
            },
        }

    def _inspect_dns_record(
        self,
        *,
        context: _DeleteContext,
        gcp_deploy_key: str | None,
        expected_ip_address: str,
    ) -> dict[str, Any]:
        access_token, timeout_seconds = self._resolve_google_access_token(
            gcp_deploy_key=gcp_deploy_key,
            stage="site_delete_dns_plan",
        )
        rrsets_url = (
            "https://dns.googleapis.com/dns/v1/projects/"
            f"{urllib.parse.quote(context.dns_project_id or '', safe='')}/managedZones/"
            f"{urllib.parse.quote(context.dns_managed_zone or '', safe='')}/rrsets"
        )
        normalized_record_name = context.dns_record_name or ""

        def _fetch_rrset(record_type: str) -> dict[str, Any] | None:
            payload = _request_google_json(
                method="GET",
                url=f"{rrsets_url}?{urllib.parse.urlencode({'name': normalized_record_name, 'type': record_type})}",
                access_token=access_token,
                timeout_seconds=timeout_seconds,
                error_stage="site_delete_dns_plan",
                code_on_failure="site_delete_dependency_blocked",
                safe_message_on_failure="Managed DNS lookup failed during delete planning.",
                safe_message_on_timeout="Managed DNS lookup timed out during delete planning.",
            )
            if not isinstance(payload, dict):
                return None
            rrsets = payload.get("rrsets")
            if not isinstance(rrsets, list):
                return None
            for rrset in rrsets:
                if not isinstance(rrset, dict):
                    continue
                rrset_name = _normalize_text(rrset.get("name"), max_length=300)
                rrset_type = _normalize_text(rrset.get("type"), max_length=10)
                if rrset_name == normalized_record_name and (rrset_type or "").upper() == record_type:
                    return rrset
            return None

        cname_rrset = _fetch_rrset("CNAME")
        if cname_rrset is not None:
            return {
                "status": "blocked",
                "summary": "The managed preview hostname has a conflicting CNAME record.",
                "details": {
                    "record_name": normalized_record_name,
                    "record_type": "A",
                    "managed_zone": context.dns_managed_zone,
                    "project_id": context.dns_project_id,
                    "expected_ip": expected_ip_address,
                    "observed_ips": [],
                    "observed_ttl": None,
                },
            }
        a_rrset = _fetch_rrset("A")
        if a_rrset is None:
            return {
                "status": "not_found",
                "summary": "No managed preview DNS A record was found for the expected hostname.",
                "details": {
                    "record_name": normalized_record_name,
                    "record_type": "A",
                    "managed_zone": context.dns_managed_zone,
                    "project_id": context.dns_project_id,
                    "expected_ip": expected_ip_address,
                    "observed_ips": [],
                    "observed_ttl": None,
                },
            }
        observed_ips: list[str] = []
        raw_rrdatas = a_rrset.get("rrdatas")
        if isinstance(raw_rrdatas, list):
            for item in raw_rrdatas:
                candidate = _normalize_text(item, max_length=80)
                if candidate:
                    observed_ips.append(candidate)
        ttl_value = int(a_rrset.get("ttl") or context.dns_ttl or 300)
        if len(observed_ips) == 1 and observed_ips[0] == expected_ip_address:
            return {
                "status": "found",
                "summary": "Verified managed preview DNS A record for this site.",
                "details": {
                    "record_name": normalized_record_name,
                    "record_type": "A",
                    "managed_zone": context.dns_managed_zone,
                    "project_id": context.dns_project_id,
                    "expected_ip": expected_ip_address,
                    "observed_ips": observed_ips,
                    "observed_ttl": ttl_value,
                },
            }
        return {
            "status": "blocked",
            "summary": "Preview DNS A record exists, but its value does not match the expected managed IP.",
            "details": {
                "record_name": normalized_record_name,
                "record_type": "A",
                "managed_zone": context.dns_managed_zone,
                "project_id": context.dns_project_id,
                "expected_ip": expected_ip_address,
                "observed_ips": observed_ips,
                "observed_ttl": ttl_value,
            },
        }

    def _namespace_owned(self, *, namespace_payload: object, context: _DeleteContext) -> bool:
        if not isinstance(namespace_payload, dict):
            return False
        return self._resource_owned(payload=namespace_payload, context=context)

    def _resource_owned(self, *, payload: dict[str, Any], context: _DeleteContext) -> bool:
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            return False
        labels = metadata.get("labels")
        if not isinstance(labels, dict):
            return False
        managed_by = _normalize_text(labels.get("app.kubernetes.io/managed-by"), max_length=80)
        site_label = _normalize_text(labels.get("mbsrn.io/site-id"), max_length=80)
        repo_label = _normalize_text(labels.get("mbsrn.io/repo"), max_length=80)
        preview_label = _normalize_hostname(labels.get("mbsrn.io/preview-hostname"))
        expected_repo_label = _identifier_fragment(context.repo_name or "", fallback="", max_length=80) or None
        expected_site_label = _identifier_fragment(context.site_id, fallback="", max_length=80)
        return (
            managed_by == _MBSRN_MANAGED_LABEL
            and site_label == expected_site_label
            and (expected_repo_label is None or repo_label == expected_repo_label)
            and (context.preview_hostname is None or preview_label == context.preview_hostname)
        )
