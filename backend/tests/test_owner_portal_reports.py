from tests.helpers import (
    add_months,
    assert_response,
    build_signed_rental,
    create_person,
    create_property,
    midday,
)


def _owner_login(client, owner: dict) -> None:
    access = assert_response(
        client.post(
            "/api/finance/advanced/portal/access",
            json={"person_id": owner["id"], "label": "Portal do proprietário"},
        ),
        201,
    ).json()
    issued = assert_response(
        client.post(f"/api/finance/advanced/portal/access/{access['id']}/temporary-password")
    ).json()
    first = assert_response(
        client.post(
            "/api/tenant-portal/auth/document-login",
            json={"identifier": owner["document_number"], "password": issued["temporary_password"]},
        )
    ).json()
    assert_response(
        client.post(
            "/api/tenant-portal/auth/temporary-change",
            json={
                "identifier": owner["document_number"],
                "change_token": first["change_token"],
                "password": "SenhaRelatoriosProprietario#2026",
            },
        )
    )


def test_owner_portal_downloads_statement_and_annual_income(client):
    journey = build_signed_rental(client, publish=False)
    owner = journey["owner"]
    competence = add_months(journey["start"], 1)

    charge = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": competence.isoformat(), "lease_contract_id": journey["lease"]["id"]},
        )
    ).json()["charges"][0]
    assert_response(
        client.post(
            f"/api/finance/charges/{charge['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": midday(competence.replace(day=10)).isoformat(),
                "payment_method": "pix",
                "payment_reference": "OWNER-PORTAL-PDF",
                "notes": "Pagamento usado para validar os PDFs do proprietário.",
            },
        )
    )

    other_owner = create_person(
        client,
        name="Outro Proprietário Portal",
        document="83838383839",
        email="outro.owner.portal@example.com",
        role_keys=["owner"],
    )
    other_property = create_property(client, other_owner["id"])
    _owner_login(client, owner)

    statement = client.get(
        f"/api/owner-portal/statements/{competence.isoformat()}/pdf",
        params={"property_id": journey["property"]["id"]},
    )
    assert statement.status_code == 200
    assert statement.headers["content-type"].startswith("application/pdf")
    assert "prestacao-contas-" in statement.headers.get("content-disposition", "")
    assert statement.content.startswith(b"%PDF")

    annual = client.get(f"/api/owner-portal/reports/{competence.year}/income.pdf")
    assert annual.status_code == 200
    assert annual.headers["content-type"].startswith("application/pdf")
    assert "informe-rendimentos-" in annual.headers.get("content-disposition", "")
    assert annual.content.startswith(b"%PDF")

    forbidden_property = client.get(
        f"/api/owner-portal/statements/{competence.isoformat()}/pdf",
        params={"property_id": other_property["id"]},
    )
    assert forbidden_property.status_code == 404
