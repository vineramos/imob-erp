from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

# Proteção deliberada: esta suíte destrói/recria dados entre testes e jamais pode
# apontar para Neon DEV/produção ou qualquer banco que não seja explicitamente de teste.
raw_database_url = os.getenv("DATABASE_URL", "").strip()
if not raw_database_url:
    pytest.exit("DATABASE_URL de teste é obrigatória para executar a suíte de integração.")
try:
    database_name = make_url(raw_database_url).database or ""
except Exception as exc:  # pragma: no cover - proteção de bootstrap
    pytest.exit(f"DATABASE_URL de teste inválida: {exc}")
if "test" not in database_name.lower():
    pytest.exit(
        f"Execução bloqueada: o banco '{database_name}' não parece ser um banco de teste. "
        "Use um database dedicado contendo 'test' no nome."
    )

from app.api.routes import contracts as contracts_routes  # noqa: E402
from app.api.routes import documents as documents_routes  # noqa: E402
from app.api.routes import inspections as inspections_routes  # noqa: E402
from app.api.routes import finance_commissions as finance_commissions_routes  # noqa: E402
from app.api.routes import leases as leases_routes  # noqa: E402
from app.api.routes import property_media as property_media_routes  # noqa: E402
from app.core.database import SessionLocal, engine  # noqa: E402
from app.domains.foundation.access import UserContext, get_current_user_context  # noqa: E402
from app.domains.foundation.models import AppUser, Organization, OrganizationSettings, Role  # noqa: E402
from app.main import app  # noqa: E402


ALL_TEST_PERMISSIONS = frozenset(
    {
        "dashboard.view",
        "properties.view",
        "properties.create",
        "properties.edit",
        "properties.publish",
        "captures.view",
        "captures.manage",
        "contracts.view",
        "contracts.create",
        "contracts.edit",
        "contracts.approve",
        "contracts.send_signature",
        "inspections.view",
        "inspections.manage",
        "maintenance.view",
        "maintenance.manage",
        "finance.view",
        "finance.charge.create",
        "finance.reconcile",
        "finance.payment.prepare",
        "finance.payment.approve",
        "finance.payment.execute",
        "finance.period.close",
        "finance.period.reopen",
        "finance.adjustment.create",
        "finance.sod.override",
        "finance.repasse.execute",
        "agenda.view",
        "agenda.manage",
        "documents.view",
        "documents.manage",
        "reports.view",
        "reports.export",
        "settings.view",
        "settings.company.manage",
        "settings.appearance.manage",
        "users.manage",
        "permissions.manage",
        "approval_rules.manage",
        "audit.view",
    }
)


@dataclass
class FakeDocumentStorage:
    configured: bool = True
    objects: dict[str, bytes] = field(default_factory=dict)

    def _name(self, prefix: str, **kwargs: Any) -> str:
        filename = str(kwargs.get("filename") or "document.bin")
        return f"tests/{prefix}/{filename}"

    def object_name(self, **kwargs: Any) -> str:
        return self._name("contracts", **kwargs)

    def property_photo_object_name(self, **kwargs: Any) -> str:
        return self._name("properties", **kwargs)

    def inspection_object_name(self, **kwargs: Any) -> str:
        return self._name("inspections", **kwargs)

    def upload_bytes(self, *, object_name: str, content: bytes, content_type: str) -> str:
        reference = f"fake://{object_name}"
        self.objects[reference] = bytes(content)
        return reference

    def download_bytes(self, reference: str) -> bytes:
        return self.objects.get(reference, b"%PDF-1.4\n% fake document\n")


@dataclass
class FakeSignatureProvider:
    configured: bool = True
    envelopes: int = 0
    documents: int = 0
    signers: int = 0

    def create_empty_envelope(self, name: str) -> str:
        self.envelopes += 1
        return f"test-envelope-{self.envelopes}"

    def upload_pdf(self, envelope_id: str, *, filename: str, content: bytes, metadata: dict | None = None) -> str:
        self.documents += 1
        assert content.startswith(b"%PDF")
        return f"test-document-{self.documents}"

    def create_signer(self, envelope_id: str, signer: dict) -> str:
        self.signers += 1
        return f"test-signer-{self.signers}"

    def create_signature_requirements(self, envelope_id: str, *, document_id: str, signer_id: str, role: str) -> None:
        return None

    def activate_envelope(self, envelope_id: str) -> None:
        return None

    def signed_document_bytes(self, envelope_id: str, document_id: str) -> bytes:
        return b"%PDF-1.4\n% documento assinado pelo provider de teste\n%%EOF"


@pytest.fixture(autouse=True)
def clean_database():
    if engine is None or SessionLocal is None:  # pragma: no cover - protegido acima
        raise RuntimeError("Engine de teste não inicializada")
    with engine.begin() as connection:
        tables = list(
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            ).scalars()
        )
        if tables:
            names = ", ".join(f'"{name}"' for name in tables)
            connection.exec_driver_sql(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE")
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def fake_integrations(monkeypatch: pytest.MonkeyPatch):
    storage = FakeDocumentStorage()
    signature = FakeSignatureProvider()

    for module in (property_media_routes, contracts_routes, leases_routes, inspections_routes, documents_routes, finance_commissions_routes):
        monkeypatch.setattr(module, "get_document_storage", lambda storage=storage: storage)
    monkeypatch.setattr(contracts_routes, "get_signature_provider", lambda _key: signature)
    monkeypatch.setattr(leases_routes, "get_signature_provider", lambda _key: signature)
    return {"storage": storage, "signature": signature}


@pytest.fixture
def identity(fake_integrations):
    assert SessionLocal is not None
    with SessionLocal() as db:
        organization = Organization(
            legal_name="Imob Testes Ltda",
            display_name="Imob Testes",
            document_number="00.000.000/0001-00",
            contact_email="testes@imob.invalid",
            contact_phone="(41) 3000-0000",
            address={"city": "Curitiba", "state": "PR"},
            is_active=True,
        )
        db.add(organization)
        db.flush()

        role = Role(
            organization_id=organization.id,
            key="admin",
            name="Administrador",
            description="Administrador dos testes automatizados",
            is_system=True,
            is_active=True,
        )
        db.add(role)
        db.flush()

        user = AppUser(
            organization_id=organization.id,
            auth_user_id="integration-test-admin",
            name="Administrador de Testes",
            email="admin.testes@imob.invalid",
            is_active=True,
        )
        user.roles.append(role)
        db.add(user)
        db.flush()

        settings = OrganizationSettings(
            organization_id=organization.id,
            erp_theme={},
            site_theme={},
            operational_defaults={},
            integrations={"signature_provider": "clicksign", "public_site_enabled": False},
            updated_by_user_id=user.id,
        )
        db.add(settings)
        db.commit()
        db.refresh(organization)
        db.refresh(user)
        _ = list(user.roles)

        context = UserContext(user=user, permission_keys=ALL_TEST_PERMISSIONS)
        organization_id = organization.id
        user_id = user.id

    def override_context() -> UserContext:
        return context

    app.dependency_overrides[get_current_user_context] = override_context
    return {
        "organization_id": organization_id,
        "user_id": user_id,
        "context": context,
        "integrations": fake_integrations,
    }


@pytest.fixture
def client(identity):
    with TestClient(app) as test_client:
        yield test_client
