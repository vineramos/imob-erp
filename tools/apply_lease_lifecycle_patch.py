from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"Marcador não encontrado em {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Lease ORM fields.
replace_once(
    "backend/app/domains/leases/models.py",
    "    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)\n    termination_fine_months:",
    "    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)\n    operational_end_date: Mapped[date | None] = mapped_column(Date, index=True)\n    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)\n    termination_fine_months:",
)

# Lease API schemas.
replace_once(
    "backend/app/domains/leases/schemas.py",
    'LeaseStatus = Literal["draft", "review", "approved", "pending_signature", "signed", "cancelled"]',
    'LeaseStatus = Literal["draft", "review", "approved", "pending_signature", "signed", "closed", "cancelled"]',
)
replace_once(
    "backend/app/domains/leases/schemas.py",
    "    end_date: date\n    termination_fine_months: Decimal",
    "    end_date: date\n    operational_end_date: date | None = None\n    closed_at: datetime | None = None\n    termination_fine_months: Decimal",
)

# Existing lease routes: response + permit a future contract once prior one is closed.
replace_once(
    "backend/app/api/routes/leases.py",
    "        end_date=item.end_date,\n        termination_fine_months=item.termination_fine_months,",
    "        end_date=item.end_date,\n        operational_end_date=item.operational_end_date,\n        closed_at=item.closed_at,\n        termination_fine_months=item.termination_fine_months,",
)
replace_once(
    "backend/app/api/routes/leases.py",
    '            LeaseContract.status.not_in(("cancelled",)),',
    '            LeaseContract.status.not_in(("cancelled", "closed")),',
)

# Stop automatic charges after an early termination date.
replace_once(
    "backend/app/domains/finance/service.py",
    "        and lease.end_date >= competence\n",
    "        and (lease.operational_end_date or lease.end_date) >= competence\n",
)

# Alembic metadata loader.
replace_once(
    "backend/migrations/env.py",
    "from app.domains.leases import models as lease_models  # noqa: F401\n",
    "from app.domains.leases import models as lease_models  # noqa: F401\nfrom app.domains.lease_lifecycle import models as lease_lifecycle_models  # noqa: F401\n",
)

# API router.
replace_once(
    "backend/app/api/router.py",
    "from app.api.routes.leases import router as leases_router\n",
    "from app.api.routes.leases import router as leases_router\nfrom app.api.routes.lease_lifecycle import router as lease_lifecycle_router\n",
)
replace_once(
    "backend/app/api/router.py",
    "api_router.include_router(leases_router)\n",
    "api_router.include_router(leases_router)\napi_router.include_router(lease_lifecycle_router)\n",
)

# Remove an intermediate no-op left during construction.
route_path = Path("backend/app/api/routes/lease_lifecycle.py")
route_text = route_path.read_text(encoding="utf-8")
route_text = route_text.replace('    item.property_disposition = "available" if False else None\n', "")
route_path.write_text(route_text, encoding="utf-8")

# Lease Contracts frontend integration.
replace_once(
    "frontend/src/modules/contracts/LeaseContractsPage.tsx",
    "import { SignatureTimeline } from './SignatureTimeline'\n",
    "import { SignatureTimeline } from './SignatureTimeline'\nimport { LeaseLifecyclePanel } from './LeaseLifecyclePanel'\n",
)
replace_once(
    "frontend/src/modules/contracts/LeaseContractsPage.tsx",
    "type LeaseStatus = 'draft' | 'review' | 'approved' | 'pending_signature' | 'signed' | 'cancelled'",
    "type LeaseStatus = 'draft' | 'review' | 'approved' | 'pending_signature' | 'signed' | 'closed' | 'cancelled'",
)
replace_once(
    "frontend/src/modules/contracts/LeaseContractsPage.tsx",
    "  end_date: string\n  termination_fine_months: number",
    "  end_date: string\n  operational_end_date: string | null\n  closed_at: string | null\n  termination_fine_months: number",
)
replace_once(
    "frontend/src/modules/contracts/LeaseContractsPage.tsx",
    "  signed: 'Assinado',\n  cancelled: 'Cancelado',",
    "  signed: 'Assinado',\n  closed: 'Encerrado',\n  cancelled: 'Cancelado',",
)
replace_once(
    "frontend/src/modules/contracts/LeaseContractsPage.tsx",
    "  if (value === 'signed' || value === 'approved') return 'success'",
    "  if (value === 'signed' || value === 'approved' || value === 'closed') return 'success'",
)
replace_once(
    "frontend/src/modules/contracts/LeaseContractsPage.tsx",
    "  const [expandedTab, setExpandedTab] = useState<'details' | 'documents'>('details')",
    "  const [expandedTab, setExpandedTab] = useState<'details' | 'lifecycle' | 'documents'>('details')",
)
replace_once(
    "frontend/src/modules/contracts/LeaseContractsPage.tsx",
    "() => properties.filter((property) => property.owners.length > 0 && !items.some((contract) => contract.property_id === property.id && contract.status !== 'cancelled')),",
    "() => properties.filter((property) => property.owners.length > 0 && !items.some((contract) => contract.property_id === property.id && !['cancelled', 'closed'].includes(contract.status))),",
)
replace_once(
    "frontend/src/modules/contracts/LeaseContractsPage.tsx",
    "<button type=\"button\" className={expandedTab==='details'?'active':''} onClick={()=>setExpandedTab('details')}>Detalhes</button><button type=\"button\" className={expandedTab==='documents'?'active':''} onClick={()=>setExpandedTab('documents')}>Documentos</button>",
    "<button type=\"button\" className={expandedTab==='details'?'active':''} onClick={()=>setExpandedTab('details')}>Detalhes</button><button type=\"button\" className={expandedTab==='lifecycle'?'active':''} onClick={()=>setExpandedTab('lifecycle')}>Ciclo da locação</button><button type=\"button\" className={expandedTab==='documents'?'active':''} onClick={()=>setExpandedTab('documents')}>Documentos</button>",
)
replace_once(
    "frontend/src/modules/contracts/LeaseContractsPage.tsx",
    "</div>}{expandedTab==='documents'&&<EntityDocumentsPanel entityType=\"lease_contract\" entityId={item.id} entityLabel={item.code} permissions={permissions} compact/>}</>}",
    "</div>}{expandedTab==='lifecycle'&&<LeaseLifecyclePanel lease={item} permissions={permissions} onChanged={()=>void load()}/>}\n              {expandedTab==='documents'&&<EntityDocumentsPanel entityType=\"lease_contract\" entityId={item.id} entityLabel={item.code} permissions={permissions} compact/>}</>}",
)

# Vistorias now visibly support both entry and exit records. Manual creation remains initial-only.
replace_once(
    "frontend/src/modules/inspections/InspectionsPage.tsx",
    "<span className=\"eyebrow\">Operação · Entrada da locação</span><h1>Vistorias</h1><p>Laudo inicial versionado, fotos, contestação e entrega de chaves vinculados ao contrato assinado.</p>",
    "<span className=\"eyebrow\">Operação · Entrada e saída</span><h1>Vistorias</h1><p>Laudos de entrada e saída versionados, com fotos e histórico vinculados ao contrato assinado.</p>",
)
replace_once(
    "frontend/src/modules/inspections/InspectionsPage.tsx",
    "<span>VISTORIA</span><strong>{item.code}</strong>",
    "<span>{item.inspection_type==='final'?'VISTORIA DE SAÍDA':'VISTORIA INICIAL'}</span><strong>{item.code}</strong>",
)

print("Lease lifecycle patch applied successfully")
