from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.portfolio.models import EconomicIndexSyncState, EconomicIndexValue


@dataclass(frozen=True)
class IndexDefinition:
    code: str
    name: str
    sgs_code: int


INDEX_DEFINITIONS: dict[str, IndexDefinition] = {
    "IPCA": IndexDefinition("IPCA", "Índice Nacional de Preços ao Consumidor Amplo", 433),
    "INPC": IndexDefinition("INPC", "Índice Nacional de Preços ao Consumidor", 188),
    "IGP-M": IndexDefinition("IGP-M", "Índice Geral de Preços - Mercado", 189),
    "IGP-DI": IndexDefinition("IGP-DI", "Índice Geral de Preços - Disponibilidade Interna", 190),
    "IPC-FIPE": IndexDefinition("IPC-FIPE", "Índice de Preços ao Consumidor - FIPE", 193),
}

HISTORY_FLOOR = date(2025, 1, 1)


class BcbSgsIndexProvider:
    base_url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series}/dados"

    def fetch(self, definition: IndexDefinition, start: date, end: date) -> list[tuple[date, Decimal]]:
        url = self.base_url.format(series=definition.sgs_code)
        params = {
            "formato": "json",
            "dataInicial": start.strftime("%d/%m/%Y"),
            "dataFinal": end.strftime("%d/%m/%Y"),
        }
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()

        rows: list[tuple[date, Decimal]] = []
        for item in payload:
            raw_date = str(item.get("data", ""))
            raw_value = str(item.get("valor", ""))
            if not raw_date or not raw_value:
                continue
            observed_at = datetime.strptime(raw_date, "%d/%m/%Y").date()
            competence = date(observed_at.year, observed_at.month, 1)
            rows.append((competence, Decimal(raw_value.replace(",", "."))))
        return rows


def _retry_at(now: datetime, retry_count: int) -> datetime:
    if retry_count <= 3:
        return now + timedelta(hours=4)
    return now + timedelta(hours=20)


def sync_index(db: Session, index_code: str, provider: BcbSgsIndexProvider | None = None) -> dict:
    definition = INDEX_DEFINITIONS.get(index_code)
    if definition is None:
        raise ValueError(f"Índice não suportado: {index_code}")

    provider = provider or BcbSgsIndexProvider()
    now = datetime.now(timezone.utc)
    state = db.scalar(select(EconomicIndexSyncState).where(EconomicIndexSyncState.index_code == index_code))
    if state is None:
        state = EconomicIndexSyncState(index_code=index_code, status="never", retry_count=0)
        db.add(state)
        db.flush()

    state.last_attempt_at = now
    start = HISTORY_FLOOR
    end = now.date()

    try:
        rows = provider.fetch(definition, start, end)
    except Exception as exc:
        state.retry_count += 1
        state.status = "error"
        state.last_error = str(exc)[:2000]
        state.next_retry_at = _retry_at(now, state.retry_count)
        db.commit()
        return {
            "index_code": index_code,
            "status": state.status,
            "imported": 0,
            "latest_competence": state.last_success_competence,
            "next_retry_at": state.next_retry_at,
            "message": "Falha ao consultar o Banco Central; nova tentativa foi programada.",
        }

    imported = 0
    latest_competence: date | None = None
    source_reference = BcbSgsIndexProvider.base_url.format(series=definition.sgs_code)
    for competence, monthly_rate in rows:
        latest_competence = max(latest_competence, competence) if latest_competence else competence
        existing = db.scalar(
            select(EconomicIndexValue).where(
                EconomicIndexValue.index_code == index_code,
                EconomicIndexValue.competence == competence,
            )
        )
        if existing is None:
            db.add(
                EconomicIndexValue(
                    index_code=index_code,
                    sgs_code=definition.sgs_code,
                    competence=competence,
                    monthly_rate=monthly_rate,
                    source="BCB/SGS",
                    source_reference=source_reference,
                )
            )
            imported += 1
        elif existing.monthly_rate != monthly_rate:
            existing.monthly_rate = monthly_rate
            existing.fetched_at = now

    previous_success = state.last_success_competence
    if latest_competence and (previous_success is None or latest_competence > previous_success or imported > 0):
        state.last_success_competence = latest_competence
        state.retry_count = 0
        state.status = "synced"
        state.next_retry_at = None
        state.last_error = None
        message = "Série atualizada com sucesso a partir do Banco Central."
    else:
        state.retry_count += 1
        state.status = "awaiting_publication"
        state.next_retry_at = _retry_at(now, state.retry_count)
        state.last_error = None
        message = "Nenhuma competência nova foi publicada; nova consulta foi programada."

    db.commit()
    return {
        "index_code": index_code,
        "status": state.status,
        "imported": imported,
        "latest_competence": state.last_success_competence,
        "next_retry_at": state.next_retry_at,
        "message": message,
    }


def cumulative_factor(values: list[Decimal]) -> Decimal:
    factor = Decimal("1")
    for rate in values:
        factor *= Decimal("1") + (rate / Decimal("100"))
    return factor
