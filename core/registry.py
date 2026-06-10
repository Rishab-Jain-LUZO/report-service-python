from typing import Dict, Type
from core.base import BaseExporter
from exporters.all_appointment_summary import AppointmentSummaryExporter
from exporters.salon_wise_appointments import SalonWiseAppointmentsExporter
from exporters.all_appointments import AllAppointmentsExporter
from exporters.completion_rate import CompletionRateExporter
from exporters.salon_head_passbook import SalonHeadPassbookExporter
from exporters.partner_rm_list import PartnerRmListExporter
from exporters.notes_list import NotesListExporter
from exporters.lead_list import LeadListExporter
from exporters.salon_offers import SalonOfferExporter
from exporters.giftcard_transactions import GiftCardTransactionExporter

# Registry of registries mapping export categories to their respective report classes
CATEGORY_REGISTRY: Dict[str, Dict[str, Type[BaseExporter]]] = {
    "appointments": {
        "summary": AppointmentSummaryExporter,
        "salon_wise": SalonWiseAppointmentsExporter,
        "all_list": AllAppointmentsExporter,
        "completion_rate": CompletionRateExporter,
    },
    "salon_heads": {
        "passbook": SalonHeadPassbookExporter,
    },
    "regional_managers": {
        "partner_rm_list": PartnerRmListExporter,
        "notes_list": NotesListExporter,
        "completion_rate": CompletionRateExporter,
    },
    "leads": {
        "leads_list": LeadListExporter,
    },
    "offers": {
        "offers_list": SalonOfferExporter,
    },
    "giftcards": {
        "transactions_list": GiftCardTransactionExporter,
    }
}
