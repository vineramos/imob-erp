ERP_THEME_DEFAULT = {
    "companyName": "Imobiliária",
    "companyShortName": "Imob",
    "logoUrl": "",
    "faviconUrl": "",
    "primary": "#123a6b",
    "primaryStrong": "#0d2d55",
    "primarySoft": "#edf4fb",
    "sidebarBg": "#ffffff",
    "appBg": "#f7f9fc",
    "surface": "#ffffff",
    "text": "#172033",
    "textMuted": "#6a7485",
    "border": "#e4e9f0",
    "success": "#2d8b57",
    "warning": "#d98b24",
    "danger": "#c84444",
    "fontFamily": 'Inter, Aptos, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    "radius": 12,
    "fieldHeight": 42,
    "sidebarWidth": 248,
    "tableDensity": "normal",
}

# Padrões já validados para novos registros/contratos. O princípio da aplicação
# continua sendo: configuração define o padrão; cada registro operacional guarda
# sua própria regra e alterações posteriores não são retroativas.
OPERATIONAL_DEFAULTS = {
    "rent_due_day": 10,
    "owner_repasse_business_days": 2,
    "residential_lease_months": 30,
    "adjustment_index": "IPCA",
    "termination_fine_months": 3,
    "inspection_contest_days": 5,
    "default_admin_fee_percent": 10,
    "delinquency_first_contact_day": 1,
    "delinquency_followup_day": 3,
    "delinquency_critical_day": 5,
    # Mora padrão para NOVOS contratos. Contratos já assinados preservam a
    # condição congelada em sua própria versão e nunca herdam mudanças futuras.
    "late_fee_percent": 2,
    "late_interest_percent_monthly": 1,
    "late_interest_type": "simple",
    "late_interest_compounding": "daily",
}

INTEGRATIONS_DEFAULTS = {
    "bank_provider": "inter",
    "signature_provider": "clicksign",
    "email_provider": "smtp",
    "public_site_enabled": False,
    "webhook_base_url": "",
    "notes": "",
}
