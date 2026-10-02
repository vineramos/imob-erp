def test_multibank_foundation_keeps_accounts_provider_agnostic_and_secrets_out_of_config(client):
    catalog_response = client.get("/api/finance/bank-setup/catalog")
    assert catalog_response.status_code == 200, catalog_response.text
    catalog = {item["key"]: item for item in catalog_response.json()}
    assert {"bb", "itau", "santander", "bradesco", "caixa", "sicredi", "sicoob", "inter", "other"}.issubset(catalog)
    assert catalog["bb"]["api_status"] == "planned"
    assert catalog["bb"]["implemented_capabilities"] == []
    assert catalog["inter"]["api_status"] == "legacy_available"
    assert catalog["inter"]["account_scoped_api"] is False
    assert {"statement", "balance", "billing", "pix_payment"}.issubset(catalog["inter"]["implemented_capabilities"])

    bb_response = client.post(
        "/api/finance/bank-setup/accounts",
        json={
            "institution_key": "bb",
            "name": "Recebimentos e repasses",
            "branch": "1234",
            "account_number": "98765",
            "account_digit": "4",
            "account_purpose": "rent_receipts_repasses",
            "fund_scope": "operating",
            "integration_mode": "api",
            "environment": "sandbox",
            "provider_account_id": "convenio-bb-teste",
            "pix_key": "financeiro@imob.invalid",
            "opening_balance": "1000.00",
        },
    )
    assert bb_response.status_code == 201, bb_response.text
    bb = bb_response.json()
    assert bb["account"]["bank_name"] == "Banco do Brasil"
    assert bb["account"]["bank_code"] == "001"
    # A finalidade de recebimento/repasse sempre força recursos de terceiros.
    assert bb["account"]["fund_scope"] == "third_party"
    # Enquanto o adaptador BB não existe, o core legado permanece neutro/manual.
    assert bb["account"]["core_provider"] == "manual"
    assert bb["setup"]["provider_key"] == "bb"
    assert bb["setup"]["integration_mode"] == "api"
    assert bb["setup"]["status"] == "api_provider_pending"
    assert bb["setup"]["enabled_capabilities"] == []

    bb_id = bb["account"]["id"]
    update_response = client.put(
        f"/api/finance/bank-setup/accounts/{bb_id}",
        json={
            "account_purpose": "rent_receipts_repasses",
            "integration_mode": "api",
            "environment": "production",
            "provider_account_id": "convenio-bb-producao",
            "credential_secret_ref": "projects/imob/secrets/bb-oauth/latest",
            "certificate_secret_ref": "projects/imob/secrets/bb-mtls-pfx/latest",
            "webhook_secret_ref": "projects/imob/secrets/bb-webhook/latest",
            "non_secret_config": {
                "client_id": "client-id-publico-de-teste",
                "agreement_code": "1234567",
            },
            "enabled_capabilities": ["billing", "pix_payment"],
        },
    )
    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["setup"]["status"] == "api_provider_pending"
    assert updated["setup"]["credential_secret_ref"].endswith("/bb-oauth/latest")
    assert updated["setup"]["certificate_secret_ref"].endswith("/bb-mtls-pfx/latest")
    assert updated["setup"]["webhook_secret_ref"].endswith("/bb-webhook/latest")
    assert updated["setup"]["non_secret_config"]["client_id"] == "client-id-publico-de-teste"
    # Capacidade só pode ser habilitada quando há adaptador implementado no Imob.
    assert updated["setup"]["enabled_capabilities"] == []

    secret_rejection = client.put(
        f"/api/finance/bank-setup/accounts/{bb_id}",
        json={
            "account_purpose": "rent_receipts_repasses",
            "integration_mode": "api",
            "environment": "production",
            "non_secret_config": {"client_secret": "isto-nao-pode-ficar-no-banco"},
            "enabled_capabilities": [],
        },
    )
    assert secret_rejection.status_code == 422
    assert "Secret Manager" in secret_rejection.json()["detail"]

    sicoob_response = client.post(
        "/api/finance/bank-setup/accounts",
        json={
            "institution_key": "sicoob",
            "name": "Conta operacional Sicoob",
            "account_purpose": "operating",
            "fund_scope": "third_party",
            "integration_mode": "import",
            "environment": "production",
            "opening_balance": "0.00",
        },
    )
    assert sicoob_response.status_code == 201, sicoob_response.text
    sicoob = sicoob_response.json()
    assert sicoob["account"]["bank_code"] == "756"
    # A finalidade operacional força caixa próprio, mesmo se o payload pedir o contrário.
    assert sicoob["account"]["fund_scope"] == "operating"
    assert sicoob["setup"]["integration_mode"] == "import"
    assert sicoob["setup"]["environment"] == "manual"
    assert sicoob["setup"]["status"] == "import_ready"

    inter_response = client.post(
        "/api/finance/bank-setup/accounts",
        json={
            "institution_key": "inter",
            "name": "Inter legado",
            "account_purpose": "operating",
            "integration_mode": "api",
            "environment": "sandbox",
            "opening_balance": "0.00",
        },
    )
    assert inter_response.status_code == 201, inter_response.text
    inter = inter_response.json()
    assert inter["account"]["core_provider"] == "inter"
    assert inter["setup"]["status"] == "api_legacy_adapter"
    assert "configuração global" in inter["setup"]["last_test_message"]
    assert inter["institution"]["account_scoped_api"] is False

    list_response = client.get("/api/finance/bank-setup/accounts")
    assert list_response.status_code == 200, list_response.text
    accounts = list_response.json()
    assert len(accounts) == 3
    assert {item["institution"]["key"] for item in accounts} == {"bb", "sicoob", "inter"}
    assert sum(item["account"]["fund_scope"] == "third_party" for item in accounts) == 1
