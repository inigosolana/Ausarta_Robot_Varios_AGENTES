from models.schemas import CampaignWebhookLead
from services.campaign_webhook_service import _normalize_leads


def test_normalize_leads_dedupes_phones():
    leads = _normalize_leads(
        [
            CampaignWebhookLead(phone_number="+34 621 11 22 33", customer_name="Ana"),
            CampaignWebhookLead(phone_number="+34621112233", customer_name="Ana dup"),
            CampaignWebhookLead(phone_number="", customer_name="Vacío"),
        ]
    )
    assert len(leads) == 1
    assert leads[0]["phone_number"] == "+34621112233"
    assert leads[0]["customer_name"] == "Ana"


def test_normalize_leads_default_customer_name():
    leads = _normalize_leads([CampaignWebhookLead(phone_number="600112233")])
    assert leads[0]["customer_name"] == "Cliente"
