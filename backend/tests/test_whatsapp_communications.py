from app.api.routes import communications as communication_routes
from app.domains.foundation.access import UserContext, get_current_user_context
from app.integrations.whatsapp import WhatsAppSendResult
from app.main import app


COMMUNICATION_PERMISSIONS = frozenset({"communications.view", "communications.manage", "communications.send"})


def _enable_permissions(identity):
    context = identity["context"]
    expanded = UserContext(user=context.user, permission_keys=context.permission_keys | COMMUNICATION_PERMISSIONS)
    app.dependency_overrides[get_current_user_context] = lambda: expanded


def test_whatsapp_cloud_send_and_delivery_webhook(client, identity, monkeypatch):
    _enable_permissions(identity)
    sent_payloads = []
    monkeypatch.setattr(communication_routes, "whatsapp_configured", lambda: True)
    monkeypatch.setattr(communication_routes, "whatsapp_webhook_configured", lambda: True)
    monkeypatch.setattr(
        communication_routes,
        "send_whatsapp_text",
        lambda **kwargs: sent_payloads.append(kwargs) or WhatsAppSendResult(message_id="wamid.TESTE-123", wa_id="5541999990000"),
    )

    created = client.post(
        "/api/communications/messages",
        json={
            "recipient_name": "Cliente WhatsApp",
            "recipient_phone": "41999990000",
            "recipient_role": "tenant",
            "channel": "whatsapp",
            "category": "manual",
            "subject": "",
            "body": "Mensagem revisada manualmente",
        },
    )
    assert created.status_code == 201
    message_id = created.json()["id"]
    assert created.json()["send_allowed"] is True

    delivered = client.post(f"/api/communications/messages/{message_id}/send")
    assert delivered.status_code == 200
    payload = delivered.json()
    assert payload["status"] == "sent"
    assert payload["provider_name"] == "meta_whatsapp_cloud"
    assert payload["provider_message_id"] == "wamid.TESTE-123"
    assert sent_payloads == [{"recipient": "41999990000", "text_body": "Mensagem revisada manualmente"}]

    monkeypatch.setattr(communication_routes, "verify_whatsapp_webhook_signature", lambda raw, signature: True)
    webhook = client.post(
        "/api/communications/whatsapp/webhook",
        headers={"x-hub-signature-256": "sha256=fake"},
        json={
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "waba-test",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.TESTE-123",
                                        "status": "delivered",
                                        "timestamp": "1788700000",
                                        "recipient_id": "5541999990000",
                                    }
                                ]
                            },
                        }
                    ],
                }
            ],
        },
    )
    assert webhook.status_code == 200
    assert webhook.json()["matched_messages"] == 1

    detail = client.get(f"/api/communications/messages/{message_id}")
    assert detail.status_code == 200
    events = detail.json()["events"]
    assert any(event["event_type"] == "whatsapp_delivered" for event in events)


def test_whatsapp_webhook_verification_and_signature_rejection(client, monkeypatch):
    monkeypatch.setattr(communication_routes, "verify_whatsapp_webhook_challenge", lambda **kwargs: "123456")
    verified = client.get(
        "/api/communications/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "verify", "hub.challenge": "123456"},
    )
    assert verified.status_code == 200
    assert verified.text == "123456"

    monkeypatch.setattr(communication_routes, "whatsapp_webhook_configured", lambda: True)
    monkeypatch.setattr(communication_routes, "verify_whatsapp_webhook_signature", lambda raw, signature: False)
    rejected = client.post(
        "/api/communications/whatsapp/webhook",
        headers={"x-hub-signature-256": "sha256=invalid"},
        json={"object": "whatsapp_business_account", "entry": []},
    )
    assert rejected.status_code == 401


def test_whatsapp_capability_is_truthful_when_not_configured(client, identity):
    _enable_permissions(identity)
    capability = client.get("/api/communications/capabilities")
    assert capability.status_code == 200
    whatsapp = capability.json()["whatsapp"]
    assert whatsapp["provider"] == "meta_whatsapp_cloud"
    assert whatsapp["api_version"].startswith("v")
    # O CI não injeta credenciais reais da Meta; não inventamos PASS de integração externa.
    assert whatsapp["configured"] is False
