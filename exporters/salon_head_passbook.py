import csv
import gc
from datetime import datetime
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter
from core.columns import (
    SALON_HEAD_PASSBOOK_HEADERS,
    get_lower_selected_set,
    passbook_needs_recorded_head,
    passbook_needs_salon_base,
    passbook_needs_growth_manager,
    passbook_needs_current_head,
    passbook_needs_current_wallet,
    passbook_needs_customer_base,
    passbook_needs_customer_state,
    passbook_needs_payment_base,
    passbook_needs_rzp_offers,
    passbook_needs_luzo_offer_code
)

class SalonHeadPassbookExporter(BaseExporter):
    @classmethod
    async def generate(cls, output_file, start_date: datetime, end_date: datetime, progress_callback=None, **kwargs) -> None:
        payload = kwargs.get("payload", {})
        salon_head_ids = payload.get("salonHeadIds")
        salon_head_wallet_ids = payload.get("salonHeadWalletIds")

        # Build dynamic filters to optimize query performance
        filters = []
        params = {
            "start_date": start_date.strftime("%Y-%m-%d") if start_date else None,
            "end_date": end_date.strftime("%Y-%m-%d") if end_date else None
        }

        if start_date:
            filters.append("shp.txn_date >= :start_date")
        if end_date:
            filters.append("shp.txn_date <= :end_date")
        if salon_head_ids:
            filters.append("shp.salon_head_id IN :salon_head_ids")
            params["salon_head_ids"] = tuple(salon_head_ids)
        if salon_head_wallet_ids:
            filters.append("shp.salon_head_wallet_id IN :salon_head_wallet_ids")
            params["salon_head_wallet_ids"] = tuple(salon_head_wallet_ids)

        where_clause = " AND ".join(filters) if filters else "1=1"

        # Determine requested columns
        selected_columns = payload.get("selectedColumns")
        req = get_lower_selected_set(selected_columns)

        # Essential main table fields required for calculations and filter logic:
        select_fields = [
            "shp.id",
            "shp.transaction_type",
            "shp.deleted_at",
            "shp.remark",
            "shp.salon_head_wallet_id",
            "shp.margin_used",
            "shp.commission_percentage",
            "shp.amount",
            "shp.final_amount",
            "shp.rzp_fees",
            "shp.pnl"
        ]

        # Conditionally add other shp columns depending on column selection
        if not selected_columns or "recorded head id" in req:
            select_fields.append("shp.salon_head_id")
        if not selected_columns or "salon id" in req:
            select_fields.append("shp.salon_id")
        if not selected_columns or "customer id" in req:
            select_fields.append("shp.customer_id")
        if not selected_columns or "gc amt used" in req:
            select_fields.append("shp.gc_amt_used")
        if not selected_columns or "platform fees" in req:
            select_fields.append("shp.convenience_fees")
        if not selected_columns or "cancellation fees" in req:
            select_fields.append("shp.penalty_amt")
        if not selected_columns or "amount before pg offers" in req:
            select_fields.append("shp.amt_before_pg_offers")
        if not selected_columns or "customer payment no" in req:
            select_fields.append("shp.customer_payment_no")
        if not selected_columns or "txn date" in req:
            select_fields.append("DATE_FORMAT(shp.txn_date, '%d-%m-%Y') AS txn_date_formatted")
        if not selected_columns or "txn day" in req:
            select_fields.append("DAYNAME(shp.txn_date) AS txn_day")
        if not selected_columns or "txn month" in req:
            select_fields.append("DATE_FORMAT(shp.txn_date, '%b') AS txn_month")
        if not selected_columns or "txn year" in req:
            select_fields.append("DATE_FORMAT(shp.txn_date, '%Y') AS txn_year")
        if not selected_columns or "rzp id" in req:
            select_fields.append("shp.rzp_payment_id")
        if not selected_columns or "payment id" in req:
            select_fields.append("shp.salonsurf_pro_payment_id")
        if not selected_columns or "referral/marketing codes used" in req:
            select_fields.append("shp.referral_codes_used")
        if not selected_columns or "commission sent" in req:
            select_fields.append("shp.commission_amt_sent")
        if not selected_columns or "commission received" in req:
            select_fields.append("shp.commission_amt_received")
        if not selected_columns or "deposit id" in req:
            select_fields.append("shp.deposit_id")
        if not selected_columns or "razorpay utr" in req:
            select_fields.append("shp.utr")
        if not selected_columns or "cashback used" in req:
            select_fields.append("shp.cashback_used")
        if not selected_columns or "cashback earned" in req:
            select_fields.append("shp.cashback_earned")

        joins = []

        # salon_heads sh join
        need_sh = passbook_needs_recorded_head(req, selected_columns)
        if need_sh:
            select_fields.extend([
                "sh.title AS recorded_head_title",
                "sh.scheme AS recorded_head_scheme",
                "sh.settlement_type AS recorded_head_settlement_type",
                "sh.balance_poc_at_luzo AS recorded_head_poc"
            ])
            joins.append("LEFT JOIN salon_heads sh ON sh.id = shp.salon_head_id")

        # salons s join (and regional manager, current_head, current_wallet depend on it)
        need_rm = passbook_needs_growth_manager(req, selected_columns)
        need_curr_sh = passbook_needs_current_head(req, selected_columns)
        need_curr_wallet = passbook_needs_current_wallet(req, selected_columns)

        need_s = passbook_needs_salon_base(req, selected_columns) or need_rm or need_curr_sh or need_curr_wallet

        if need_s:
            select_fields.extend([
                "s.salon_name",
                "s.salon_location",
                "s.city",
                "s.salon_area",
                "s.pincode AS salon_pincode",
                "s.is_disabled AS salon_is_disabled"
            ])
            joins.append("LEFT JOIN salons s ON s.id = shp.salon_id")

            if need_rm:
                select_fields.append("(SELECT u.name FROM users u JOIN rm_salon rms ON rms.rm_id = u.id WHERE rms.salon_id = s.id LIMIT 1) AS regional_manager_name")
            if need_curr_sh:
                select_fields.extend([
                    "curr_sh.id AS current_head_id",
                    "curr_sh.title AS current_head_title",
                    "curr_sh.scheme AS current_head_scheme",
                    "curr_sh.settlement_type AS current_head_settlement_type",
                    "curr_sh.balance_poc_at_luzo AS current_head_poc"
                ])
                joins.append("LEFT JOIN salon_heads curr_sh ON curr_sh.id = s.salon_head_id")
            if need_curr_wallet:
                select_fields.append("(SELECT GROUP_CONCAT(shw.id SEPARATOR '_') FROM salon_head_wallets shw WHERE shw.salon_head_id = s.salon_head_id AND shw.is_archived = 0) AS current_wallet_ids")

        # customers c join
        need_st = passbook_needs_customer_state(req, selected_columns)
        need_c = passbook_needs_customer_base(req, selected_columns) or need_st

        if need_c:
            select_fields.extend([
                "c.name AS customer_name",
                "c.contact AS customer_contact",
                "c.email AS customer_email",
                "c.gender AS customer_gender",
                "c.dob AS customer_dob",
                "TIMESTAMPDIFF(YEAR, c.dob, CURDATE()) AS customer_age",
                "c.app_version AS customer_app_version",
                "c.os AS customer_os",
                "c.pincode AS customer_pincode"
            ])
            joins.append("LEFT JOIN customers c ON c.id = shp.customer_id")

            if need_st:
                select_fields.append("st.name AS customer_state")
                joins.append("LEFT JOIN state st ON st.id = c.state_id")

        # salonsurf_pro_payments spp join
        need_rzp_offers = passbook_needs_rzp_offers(req, selected_columns)
        need_lou = passbook_needs_luzo_offer_code(req, selected_columns)
        need_spp = passbook_needs_payment_base(req, selected_columns) or need_rzp_offers or need_lou

        if need_spp:
            select_fields.extend([
                "spp.discount_percentage",
                "spp.cashback_percentage"
            ])
            joins.append("LEFT JOIN salonsurf_pro_payments spp ON spp.id = shp.salonsurf_pro_payment_id")

            if need_rzp_offers:
                select_fields.append("(SELECT GROUP_CONCAT(pgo.offer_id SEPARATOR ',') FROM payment_gateway_offers_used pgo WHERE pgo.payment_id = spp.payment_id) AS rzp_offers_used")
            if need_lou:
                select_fields.append("lou.luzo_offer_code")
                joins.append("LEFT JOIN luzo_offers_usages lou ON lou.salonsurf_pro_payment_id = spp.id")

        select_clause = ",\n                ".join(select_fields)
        joins_clause = "\n            ".join(joins)

        # SQL query fetching passbook records with joined descriptions
        query = text(f"""
            SELECT 
                {select_clause}
            FROM salon_head_passbooks shp
            {joins_clause}
            WHERE {where_clause}
            ORDER BY shp.id ASC
        """)

        headers = SALON_HEAD_PASSBOOK_HEADERS

        async with AsyncSessionLocal() as session:
            conn = await session.connection()

            # Pre-fetch latest credit transaction margins per wallet to handle margin computations in memory
            if salon_head_wallet_ids:
                wallet_ids = list(salon_head_wallet_ids)
            elif salon_head_ids:
                wallet_res = await conn.execute(
                    text("SELECT id FROM salon_head_wallets WHERE salon_head_id IN :sh_ids AND is_archived = 0"),
                    {"sh_ids": tuple(salon_head_ids)}
                )
                wallet_ids = [r[0] for r in wallet_res.all()]
            else:
                wallet_res = await conn.execute(text("SELECT DISTINCT salon_head_wallet_id FROM salon_head_passbooks WHERE salon_head_wallet_id IS NOT NULL"))
                wallet_ids = [r[0] for r in wallet_res.all()]
             
            latest_margins = {}
            for w_id in wallet_ids:
                margin_q = text("""
                    SELECT margin_received 
                    FROM salon_head_passbooks 
                    WHERE transaction_type = 1 AND salon_head_wallet_id = :w_id AND deleted_at IS NULL 
                    ORDER BY txn_date DESC, id DESC 
                    LIMIT 1
                """)
                res = await conn.execute(margin_q, {"w_id": w_id})
                row = res.first()
                if row and row[0] is not None:
                    latest_margins[w_id] = row[0]

            # Execute streaming passbook query
            result_stream = await conn.stream(query, params)

            writer = cls.get_csv_writer(output_file, headers, **kwargs)
            writer.writerow(headers)

            gc.disable()
            try:
                processed_count = 0
                async for partition in result_stream.partitions(1000):
                    rows_to_write = []
                    for row in partition:
                        # Replicate the skip logic of the Laravel job
                        # Skip if DEBIT (type 2) and soft-deleted with PAYMENT_SPLIT remark
                        if row.transaction_type == 2 and row.deleted_at is not None and row.remark == "PAYMENT_SPLIT":
                            continue
                        # Skip if CREDIT (type 1) and soft-deleted
                        if row.transaction_type == 1 and row.deleted_at is not None:
                            continue

                        # Resolve Transaction Label
                        txn_label = "Invalid Transaction"
                        if row.transaction_type in (2, 3):
                            txn_label = "Client Payment"
                        elif row.transaction_type == 1:
                            txn_label = "Deposit"
                        elif row.transaction_type == 4:
                            txn_label = "Giftcard Purchase"
                        elif row.transaction_type == 5:
                            txn_label = "Partner listing fees"
                        elif row.transaction_type == 6:
                            txn_label = "Membership Purchase"
                        elif row.transaction_type == 7:
                            txn_label = "Payment Refund"

                        # Resolve Margin %
                        margin_pct = None
                        if row.transaction_type == 3:
                            margin_pct = row.commission_percentage
                        elif row.transaction_type == 2:
                            margin_pct = row.margin_used if row.margin_used is not None else latest_margins.get(row.salon_head_wallet_id)

                        # Resolve PG fees (paise to rupees conversion)
                        rzp_fees_rupees = round((float(row.rzp_fees or 0) / 100.0), 2)

                        # Resolve PNL
                        pnl = row.pnl
                        if pnl is not None:
                            pnl = round(float(pnl), 2)
                        elif row.transaction_type == 2 and margin_pct is not None:
                            # Replicating Laravel's exact math formula:
                            # cost_of_service = amount - amount * (margin / 100)
                            # final_amount - cost_of_service - (rzp_fees_rupees / 100)
                            cost_service = float(row.amount or 0) - (float(row.amount or 0) * (float(margin_pct) / 100.0))
                            rzp_fees_recalc = rzp_fees_rupees / 100.0
                            pnl = round(float(row.final_amount or 0) - cost_service - rzp_fees_recalc, 2)

                        # Resolve Gross Margin
                        gross_margin = None
                        if pnl is not None and row.final_amount and float(row.final_amount) > 0:
                            gross_margin = round(((pnl / float(row.final_amount)) * 100.0), 2)

                        # Format gender
                        gender = getattr(row, "customer_gender", None)
                        if gender:
                            gender = gender.lower()

                        # Append clean row array
                        rows_to_write.append([
                            txn_label,
                            getattr(row, "salon_head_id", None),
                            getattr(row, "recorded_head_title", None) or "",
                            getattr(row, "recorded_head_scheme", None) or "",
                            getattr(row, "recorded_head_settlement_type", None) or "",
                            getattr(row, "recorded_head_poc", None) or "",
                            row.salon_head_wallet_id,
                            getattr(row, "salon_id", None) or "",
                            getattr(row, "salon_name", None) or "",
                            getattr(row, "salon_location", None) or "",
                            getattr(row, "city", None) or "",
                            getattr(row, "regional_manager_name", None) or "",
                            getattr(row, "current_head_id", None) or "",
                            getattr(row, "current_head_title", None) or "",
                            getattr(row, "current_head_scheme", None) or "",
                            getattr(row, "current_head_settlement_type", None) or "",
                            getattr(row, "current_head_poc", None) or "",
                            getattr(row, "current_wallet_ids", None) or "",
                            getattr(row, "customer_id", None) or "",
                            getattr(row, "customer_name", None) or "",
                            getattr(row, "customer_contact", None) or "",
                            row.amount or 0.0,
                            getattr(row, "cashback_used", None) or 0.0,
                            getattr(row, "discount_percentage", None) or 0.0,
                            getattr(row, "convenience_fees", None) or 0.0,
                            getattr(row, "penalty_amt", None) or 0.0,
                            getattr(row, "gc_amt_used", None) or 0.0,
                            getattr(row, "amt_before_pg_offers", None) or "",
                            row.final_amount or 0.0,
                            getattr(row, "cashback_percentage", None) or 0.0,
                            getattr(row, "cashback_earned", None) or 0.0,
                            getattr(row, "luzo_offer_code", None) or "",
                            getattr(row, "rzp_offers_used", None) or "",
                            rzp_fees_rupees,
                            pnl if pnl is not None else "",
                            gross_margin if gross_margin is not None else "",
                            margin_pct if margin_pct is not None else "",
                            getattr(row, "customer_payment_no", None) or "",
                            getattr(row, "txn_date_formatted", None) or "",
                            getattr(row, "txn_day", None) or "",
                            getattr(row, "txn_month", None) or "",
                            getattr(row, "txn_year", None) or "",
                            getattr(row, "rzp_payment_id", None) or "",
                            getattr(row, "salonsurf_pro_payment_id", None) or "",
                            getattr(row, "referral_codes_used", None) or "",
                            getattr(row, "commission_amt_sent", None) or 0.0,
                            getattr(row, "commission_amt_received", None) or 0.0,
                            getattr(row, "deposit_id", None) or "",
                            getattr(row, "customer_email", None) or "",
                            gender or "",
                            getattr(row, "customer_dob", None) or "",
                            getattr(row, "customer_age", None) if getattr(row, "customer_age", None) is not None else "",
                            getattr(row, "customer_app_version", None) or "",
                            getattr(row, "customer_os", None) or "",
                            getattr(row, "customer_pincode", None) or "",
                            getattr(row, "customer_state", None) or "",
                            getattr(row, "salon_area", None) or "",
                            getattr(row, "salon_pincode", None) or "",
                            "yes" if getattr(row, "salon_is_disabled", None) else "no",
                            row.id,
                            getattr(row, "utr", None) or ""
                        ])
                    writer.writerows(rows_to_write)
                    processed_count += len(partition)
                    if progress_callback:
                        await progress_callback(processed_count)
            finally:
                gc.enable()
