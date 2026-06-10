from typing import List, Optional, Set

# ==========================================
# 1. HEADERS DEFINITIONS
# ==========================================

ALL_APPOINTMENTS_HEADERS = [
    'Appointment ID',
    'Salon Id',
    'Partner Name',
    'Partner Location',
    'Partner City',
    'Outlet Type',
    'Customer Id',
    'Customer Name',
    'Customer Contact',
    'Customer Gender',
    'Customer No. of Payments',
    'Partner Category',
    'Growth Manager',
    'Appointment Date',
    'Appointment Time',
    'Booking Date',
    'Booking Time',
    'First Action Taken By',
    'First Action Taken At',
    'First Action Taken In (Time from Booking in minutes)',
    'First Action Status',
    'Advance Booking Time (in minutes)',
    'Booked in working hours',
    'Current Status',
    'Was Confirmed',
    'Served',
    'Cancelled',
    'Cancellation Reason',
    'Cancelled By',
    'Cancelled At',
    'Was Customer near Outlet',
    'Distance from Outlet (mtrs)',
    'Appointment Source'
]

SALON_WISE_HEADERS = [
    'Code',
    'Partner ID',
    'Partner Name',
    'Partner Location',
    'City',
    'Is Disabled',
    'Total Appointments',
    'Completed Appointments',
    'Completed Appointments (%)',
    'Cancelled Appointments',
    'Cancelled Appointments (%)',
    'Cancelled by User',
    'Cancelled by User (%)',
    'Cancelled by Partner',
    'Cancelled by Partner (%)',
    'Cancelled by Automation',
    'Cancelled by Automation (%)'
]

APPOINTMENT_SUMMARY_HEADERS = [
    'Total Appointments',
    'Total Completed Appointments',
    'Completed Appointments (%)',
    'Total Cancelled Appointments',
    'Cancelled Appointments (%)',
    'Total Cancelled By User',
    'Cancelled By User (%)',
    'Total Cancelled By Salon',
    'Cancelled By Salon (%)',
    'Total Cancelled By Automation',
    'Cancelled By Automation (%)'
]

SALON_HEAD_PASSBOOK_HEADERS = [
    "Txn Type",
    "Recorded Head Id",
    "Recorded Head Name",
    "Recorded Head Scheme",
    "Recorded Head Settlement Type",
    "Recorded Head POC",
    "Recorded Head Wallet Id",
    "Salon Id",
    "Salon Name",
    "Salon Location",
    "Salon City",
    "Growth Manager",
    "Current Head Id",
    "Current Head Name",
    "Current Head Scheme",
    "Current Head Settlement Type",
    "Current Head POC",
    "Current Wallet Id",
    "Customer Id",
    "Customer Name",
    "Contact",
    "Bill/Deposit Amount",
    "Cashback Used",
    "Discount Percentage",
    "Platform Fees",
    "Cancellation Fees",
    "GC Amt Used",
    "Amount Before PG Offers",
    "Final Amt",
    "Cashback Percentage",
    "Cashback Earned",
    "Offer Code",
    "RZP Offers Used",
    "RZP Fees",
    "PNL",
    "Gross Margin",
    "Margin/Commission %",
    "Customer Payment No",
    "Txn Date",
    "Txn Day",
    "Txn Month",
    "Txn Year",
    "RZP Id",
    "Payment Id",
    "Referral/Marketing codes used",
    "Commission Sent",
    "Commission Received",
    "Deposit Id",
    "Customer Email",
    "Customer Gender",
    "Customer DOB",
    "Customer Age",
    "Customer App Version",
    "Customer OS",
    "Customer Pincode",
    "Customer State",
    "Salon Area",
    "Salon Pincode",
    "Salon Disabled",
    "Passbook Id (Used for reconciliation)",
    "Razorpay UTR"
]

PARTNER_RM_LIST_HEADERS = [
    'Partner Id',
    'Partner Name',
    'Partner Location',
    'Partner Outlet Type',
    'Partner enable  status',
    'Partner Head Title',
    'Scheme',
    'Partner Category',
    'Wallet Balance',
    'Tax: Package Amount',
    'Tax: Benefit Received',
    'Tax: Margin Received',
    'Partner POC',
    'Onboarding POC',
    'RM name',
    'Appointments Count',
    'Payments Count',
    'Total Completed Appointments',
    'Confirmation Rate',
    'Cancellation Rate',
    'Total Billing',
    'Life Time ABV',
    'PNL',
    'Latest RM Notes',
    'Starting Date',
]

NOTES_LIST_HEADERS = [
    'Head ID',
    'Head Name',
    'Partner ID',
    'Partner Name',
    'Location',
    'Growth Manager',
    'Category',
    'Subcategory',
    'Appointment Id',
    'Date',
    'Notes',
    'Note By',
]



# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================

def get_lower_selected_set(selected_columns: Optional[List[str]]) -> Set[str]:
    """Helper to convert selected columns list to a case-insensitive set."""
    if not selected_columns:
        return set()
    return {c.lower().strip() for c in selected_columns}


# --- A. Appointments Exporters Checks ---

def all_appointments_needs_customer(selected_columns: Optional[List[str]]) -> bool:
    """Checks if customer details are requested in the appointments report."""
    if not selected_columns:
        return True
    req = get_lower_selected_set(selected_columns)
    customer_cols = {"customer id", "customer name", "customer contact", "customer gender"}
    return any(x in req for x in customer_cols)


def salon_wise_needs_cancellation(selected_columns: Optional[List[str]]) -> bool:
    """Checks if cancellation metrics are requested in the salon-wise report."""
    if not selected_columns:
        return True
    req = get_lower_selected_set(selected_columns)
    cancellation_cols = {
        "cancelled by user",
        "cancelled by user (%)",
        "cancelled by partner",
        "cancelled by partner (%)",
        "cancelled by automation",
        "cancelled by automation (%)"
    }
    return any(x in req for x in cancellation_cols)


# --- B. Salon Head Passbook Exporter Checks ---

def passbook_needs_recorded_head(req: Set[str], selected_columns: Optional[List[str]]) -> bool:
    """Checks if recorded head name or details are requested."""
    if not selected_columns:
        return True
    recorded_head_cols = {
        "recorded head name",
        "recorded head scheme",
        "recorded head settlement type",
        "recorded head poc"
    }
    return any(x in req for x in recorded_head_cols)


def passbook_needs_salon_base(req: Set[str], selected_columns: Optional[List[str]]) -> bool:
    """Checks if basic salon fields or dependent metrics are requested."""
    if not selected_columns:
        return True
    salon_base_cols = {
        "salon name",
        "salon location",
        "salon city",
        "salon area",
        "salon pincode",
        "salon disabled"
    }
    return any(x in req for x in salon_base_cols)


def passbook_needs_growth_manager(req: Set[str], selected_columns: Optional[List[str]]) -> bool:
    """Checks if the growth manager column is requested."""
    if not selected_columns:
        return True
    return "growth manager" in req


def passbook_needs_current_head(req: Set[str], selected_columns: Optional[List[str]]) -> bool:
    """Checks if current head details are requested."""
    if not selected_columns:
        return True
    current_head_cols = {
        "current head id",
        "current head name",
        "current head scheme",
        "current head settlement type",
        "current head poc"
    }
    return any(x in req for x in current_head_cols)


def passbook_needs_current_wallet(req: Set[str], selected_columns: Optional[List[str]]) -> bool:
    """Checks if the current wallet ID column is requested."""
    if not selected_columns:
        return True
    return "current wallet id" in req


def passbook_needs_customer_base(req: Set[str], selected_columns: Optional[List[str]]) -> bool:
    """Checks if customer details are requested."""
    if not selected_columns:
        return True
    customer_cols = {
        "customer name",
        "contact",
        "customer email",
        "customer gender",
        "customer dob",
        "customer age",
        "customer app version",
        "customer os",
        "customer pincode"
    }
    return any(x in req for x in customer_cols)


def passbook_needs_customer_state(req: Set[str], selected_columns: Optional[List[str]]) -> bool:
    """Checks if customer state is requested."""
    if not selected_columns:
        return True
    return "customer state" in req


def passbook_needs_payment_base(req: Set[str], selected_columns: Optional[List[str]]) -> bool:
    """Checks if payment rates/percentages are requested."""
    if not selected_columns:
        return True
    payment_cols = {
        "discount percentage",
        "cashback percentage"
    }
    return any(x in req for x in payment_cols)


def passbook_needs_rzp_offers(req: Set[str], selected_columns: Optional[List[str]]) -> bool:
    """Checks if razorpay offers used are requested."""
    if not selected_columns:
        return True
    return "rzp offers used" in req


def passbook_needs_luzo_offer_code(req: Set[str], selected_columns: Optional[List[str]]) -> bool:
    """Checks if the luzo offer code is requested."""
    if not selected_columns:
        return True
    return "offer code" in req
