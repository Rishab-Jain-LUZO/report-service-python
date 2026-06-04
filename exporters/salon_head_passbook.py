import csv
import gc
from datetime import datetime
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter

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

        # SQL query fetching passbook records with joined descriptions
        query = text(f"""
            SELECT 
                shp.id,
                shp.salon_head_id,
                shp.salon_head_wallet_id,
                shp.salon_id,
                shp.customer_id,
                shp.transaction_type,
                shp.amount,
                shp.gc_amt_used,
                shp.convenience_fees,
                shp.penalty_amt,
                shp.amt_before_pg_offers,
                shp.final_amount,
                shp.cashback_used,
                shp.cashback_earned,
                shp.customer_payment_no,
                DATE_FORMAT(shp.txn_date, '%d-%m-%Y') AS txn_date_formatted,
                DAYNAME(shp.txn_date) AS txn_day,
                DATE_FORMAT(shp.txn_date, '%b') AS txn_month,
                DATE_FORMAT(shp.txn_date, '%Y') AS txn_year,
                shp.rzp_payment_id,
                shp.salonsurf_pro_payment_id,
                shp.referral_codes_used,
                shp.commission_amt_sent,
                shp.commission_amt_received,
                shp.deposit_id,
                shp.utr,
                shp.deleted_at,
                shp.remark,
                shp.commission_percentage,
                shp.margin_used,
                shp.pnl,
                shp.rzp_fees,
                sh.title AS recorded_head_title,
                sh.scheme AS recorded_head_scheme,
                sh.settlement_type AS recorded_head_settlement_type,
                sh.balance_poc_at_luzo AS recorded_head_poc,
                s.salon_name,
                s.salon_location,
                s.city,
                (SELECT u.name FROM users u JOIN rm_salon rms ON rms.rm_id = u.id WHERE rms.salon_id = s.id LIMIT 1) AS regional_manager_name,
                curr_sh.id AS current_head_id,
                curr_sh.title AS current_head_title,
                curr_sh.scheme AS current_head_scheme,
                curr_sh.settlement_type AS current_head_settlement_type,
                curr_sh.balance_poc_at_luzo AS current_head_poc,
                (SELECT GROUP_CONCAT(shw.id SEPARATOR '_') FROM salon_head_wallets shw WHERE shw.salon_head_id = s.salon_head_id AND shw.is_archived = 0) AS current_wallet_ids,
                c.name AS customer_name,
                c.contact AS customer_contact,
                c.email AS customer_email,
                c.gender AS customer_gender,
                c.dob AS customer_dob,
                TIMESTAMPDIFF(YEAR, c.dob, CURDATE()) AS customer_age,
                c.app_version AS customer_app_version,
                c.os AS customer_os,
                c.pincode AS customer_pincode,
                st.name AS customer_state,
                s.salon_area,
                s.pincode AS salon_pincode,
                s.is_disabled AS salon_is_disabled,
                (SELECT GROUP_CONCAT(pgo.offer_id SEPARATOR ',') FROM payment_gateway_offers_used pgo WHERE pgo.payment_id = spp.payment_id) AS rzp_offers_used,
                spp.discount_percentage,
                spp.cashback_percentage,
                lou.luzo_offer_code
            FROM salon_head_passbooks shp
            LEFT JOIN salon_heads sh ON sh.id = shp.salon_head_id
            LEFT JOIN salons s ON s.id = shp.salon_id
            LEFT JOIN salon_heads curr_sh ON curr_sh.id = s.salon_head_id
            LEFT JOIN customers c ON c.id = shp.customer_id
            LEFT JOIN state st ON st.id = c.state_id
            LEFT JOIN salonsurf_pro_payments spp ON spp.id = shp.salonsurf_pro_payment_id
            LEFT JOIN luzo_offers_usages lou ON lou.salonsurf_pro_payment_id = spp.id
            WHERE {where_clause}
            ORDER BY shp.id ASC
        """)

        headers = [
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

            writer = csv.writer(output_file)
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
                        gender = row.customer_gender
                        if gender:
                            gender = gender.lower()

                        # Append clean row array
                        rows_to_write.append([
                            txn_label,
                            row.salon_head_id,
                            row.recorded_head_title or "",
                            row.recorded_head_scheme or "",
                            row.recorded_head_settlement_type or "",
                            row.recorded_head_poc or "",
                            row.salon_head_wallet_id,
                            row.salon_id or "",
                            row.salon_name or "",
                            row.salon_location or "",
                            row.city or "",
                            row.regional_manager_name or "",
                            row.current_head_id or "",
                            row.current_head_title or "",
                            row.current_head_scheme or "",
                            row.current_head_settlement_type or "",
                            row.current_head_poc or "",
                            row.current_wallet_ids or "",
                            row.customer_id or "",
                            row.customer_name or "",
                            row.customer_contact or "",
                            row.amount or 0.0,
                            row.cashback_used or 0.0,
                            row.discount_percentage or 0.0,
                            row.convenience_fees or 0.0,
                            row.penalty_amt or 0.0,
                            row.gc_amt_used or 0.0,
                            row.amt_before_pg_offers or "",
                            row.final_amount or 0.0,
                            row.cashback_percentage or 0.0,
                            row.cashback_earned or 0.0,
                            row.luzo_offer_code or "",
                            row.rzp_offers_used or "",
                            rzp_fees_rupees,
                            pnl if pnl is not None else "",
                            gross_margin if gross_margin is not None else "",
                            margin_pct if margin_pct is not None else "",
                            row.customer_payment_no or "",
                            row.txn_date_formatted or "",
                            row.txn_day or "",
                            row.txn_month or "",
                            row.txn_year or "",
                            row.rzp_payment_id or "",
                            row.salonsurf_pro_payment_id or "",
                            row.referral_codes_used or "",
                            row.commission_amt_sent or 0.0,
                            row.commission_amt_received or 0.0,
                            row.deposit_id or "",
                            row.customer_email or "",
                            gender or "",
                            row.customer_dob or "",
                            row.customer_age if row.customer_age is not None else "",
                            row.customer_app_version or "",
                            row.customer_os or "",
                            row.customer_pincode or "",
                            row.customer_state or "",
                            row.salon_area or "",
                            row.salon_pincode or "",
                            "yes" if row.salon_is_disabled else "no",
                            row.id,
                            row.utr or ""
                        ])
                    writer.writerows(rows_to_write)
                    processed_count += len(partition)
                    if progress_callback:
                        await progress_callback(processed_count)
            finally:
                gc.enable()
