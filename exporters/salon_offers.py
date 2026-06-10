import gc
from datetime import datetime, timedelta
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter

class SalonOfferExporter(BaseExporter):
    @classmethod
    async def generate(cls, output_file, start_date: datetime, end_date: datetime, progress_callback=None, **kwargs) -> None:
        payload = kwargs.get("payload", {}) or {}
        
        # 1. Parse offer_type/offerType and other filters
        offer_type_filter = payload.get("offerType", "general")
        filters = payload.get("filters", {}) or {}
        
        search_term = filters.get("searchTerm")
        is_active = filters.get("is_active")
        is_deleted = filters.get("is_deleted")
        min_payment = filters.get("min_payment")
        max_payment = filters.get("max_payment")
        specific_type = filters.get("type")

        # 2. Build where clauses for luzo_offers
        where_clauses = ["s.deleted_at IS NULL"]
        params = {}
        
        # Filter by offerType
        if offer_type_filter == 'general':
            where_clauses.append("o.type = 'general'")
            
        # Filter is_active
        if is_active is not None:
            where_clauses.append("o.is_active = :is_active")
            params["is_active"] = int(is_active)
        else:
            where_clauses.append("o.is_active = 1")
            
        # Filter is_deleted
        if is_deleted is not None:
            if int(is_deleted) == 1:
                where_clauses.append("o.deleted_at IS NOT NULL")
            else:
                where_clauses.append("o.deleted_at IS NULL")
        else:
            where_clauses.append("o.deleted_at IS NULL")
            
        # Filter min_payment / max_payment
        if min_payment is not None:
            where_clauses.append("o.min_payments = :min_payment")
            params["min_payment"] = int(min_payment)
        if max_payment is not None:
            where_clauses.append("o.max_payments = :max_payment")
            params["max_payment"] = int(max_payment)
            
        # Filter specific type
        if specific_type is not None:
            where_clauses.append("o.type = :specific_type")
            params["specific_type"] = specific_type
            
        # Filter searchTerm
        if search_term:
            where_clauses.append("""
                (
                    s.salon_name LIKE :search
                    OR s.salon_location LIKE :search
                    OR s.city LIKE :search
                    OR sh.title LIKE :search
                    OR o.title LIKE :search
                    OR o.code LIKE :search
                )
            """)
            params["search"] = f"%{search_term}%"
            
        where_clause_str = " AND ".join(where_clauses)
        
        # 3. Main Query
        main_query = text(f"""
            SELECT 
                o.id AS offer_id,
                o.type AS offer_type,
                o.discount_percentage,
                o.cashback_percentage,
                o.min_payments,
                o.max_payments,
                o.usable_once,
                o.updated_at AS offer_updated_at,
                s.id AS salon_id,
                s.salon_name,
                s.salon_location,
                s.city,
                s.pincode,
                s.salon_area,
                s.is_commissionable,
                s.is_disabled,
                s.salon_head_id,
                sh.title AS head_title
            FROM luzo_offers o
            JOIN salons s ON o.salon_id = s.id
            LEFT JOIN salon_heads sh ON s.salon_head_id = sh.id
            WHERE {where_clause_str}
            ORDER BY s.id DESC, o.id DESC
        """)
        
        # Define headers
        headers = [
            'salon_id',
            '1st_discount',
            '1st_cashback',
            'weekday_discount',
            'weekday_cashback',
            'weekend_discount',
            'weekend_cashback',
            'Head Name',
            'Partner Name',
            'Partner Location',
            'Partner City',
            'Pincode',
            'Area',
            'Margin',
            'Is Enabled',
            'Offer Type',
            'Last 30 Days Payment Count',
            'Last 30 Days Billing',
            'Last Month Completion Rate',
            'Last Month Appointment Count',
            'Current Balance',
            'No. of Outlets in Head',
            'Last 30 Days PnL',
            'Growth Manager',
            'Last Updated At'
        ]

        async with AsyncSessionLocal() as session:
            conn = await session.connection()
            
            res = await conn.execute(main_query, params)
            rows = res.fetchall()
            
            if not rows:
                writer = cls.get_csv_writer(output_file, headers, **kwargs)
                writer.writerow(headers)
                return
                
            offer_ids = tuple([r.offer_id for r in rows])
            salon_ids = tuple(list(set([r.salon_id for r in rows])))
            head_ids = tuple(list(set([r.salon_head_id for r in rows if r.salon_head_id])))
            
            # Let's perform all bulk pre-fetch operations concurrently or sequentially
            # 1. Fetch validities
            validities = {}
            if offer_ids:
                val_q = text("""
                    SELECT luzo_offer_id, working_day 
                    FROM luzo_offers_validities 
                    WHERE luzo_offer_id IN :offer_ids
                """)
                val_res = await conn.execute(val_q, {"offer_ids": offer_ids})
                for r in val_res.fetchall():
                    if r.luzo_offer_id not in validities:
                        validities[r.luzo_offer_id] = []
                    validities[r.luzo_offer_id].append(r.working_day)
                    
            # 2. Fetch current balances
            balances_map = {}
            if head_ids:
                bal_q = text("""
                    SELECT salon_head_id, SUM(current_balance) AS balance 
                    FROM v_salon_head_balance 
                    WHERE salon_head_id IN :head_ids 
                    GROUP BY salon_head_id
                """)
                bal_res = await conn.execute(bal_q, {"head_ids": head_ids})
                for r in bal_res.fetchall():
                    balances_map[r.salon_head_id] = r.balance
                    
            # 3. Fetch completion metrics (last month)
            last_month = datetime.utcnow() - timedelta(days=30)
            metrics_map = {}
            if salon_ids:
                met_q = text("""
                    SELECT salon_id, completion_rate, total_appointments 
                    FROM partner_completion_metrics 
                    WHERE period_type = 'MONTH' 
                      AND year = :year 
                      AND month = :month 
                      AND salon_id IN :salon_ids
                """)
                met_res = await conn.execute(met_q, {
                    "year": last_month.year,
                    "month": last_month.month,
                    "salon_ids": salon_ids
                })
                for r in met_res.fetchall():
                    metrics_map[r.salon_id] = {
                        "completion_rate": r.completion_rate,
                        "total_appointments": r.total_appointments
                    }
                    
            # 4. Fetch latest margins
            latest_margins_map = {}
            if salon_ids:
                marg_q = text("""
                    SELECT sm.salon_id, sm.margin_percentage 
                    FROM salon_margins sm
                    INNER JOIN (
                        SELECT salon_id, MAX(created_at) AS max_created
                        FROM salon_margins
                        WHERE deleted_at IS NULL AND salon_id IN :salon_ids
                        GROUP BY salon_id
                    ) latest ON sm.salon_id = latest.salon_id AND sm.created_at = latest.max_created
                    WHERE sm.deleted_at IS NULL
                """)
                marg_res = await conn.execute(marg_q, {"salon_ids": salon_ids})
                for r in marg_res.fetchall():
                    latest_margins_map[r.salon_id] = r.margin_percentage
                    
            # 5. Fetch growth managers (RMs)
            rm_map = {}
            if salon_ids:
                rm_q = text("""
                    SELECT rms.salon_id, u.name 
                    FROM rm_salon rms 
                    JOIN users u ON rms.rm_id = u.id
                    WHERE rms.salon_id IN :salon_ids
                """)
                rm_res = await conn.execute(rm_q, {"salon_ids": salon_ids})
                for r in rm_res.fetchall():
                    if r.salon_id not in rm_map:
                        rm_map[r.salon_id] = r.name # keep first RM as first() in PHP
                        
            # 6. Fetch last 30 days PnL
            pnl_map = {}
            if salon_ids:
                pnl_date = datetime.utcnow() - timedelta(days=30)
                pnl_q = text("""
                    SELECT salon_id, SUM(pnl) AS total_pnl 
                    FROM salon_head_passbooks 
                    WHERE created_at >= :pnl_date 
                      AND deleted_at IS NULL 
                      AND salon_id IN :salon_ids
                    GROUP BY salon_id
                """)
                pnl_res = await conn.execute(pnl_q, {"pnl_date": pnl_date.strftime("%Y-%m-%d 00:00:00"), "salon_ids": salon_ids})
                for r in pnl_res.fetchall():
                    pnl_map[r.salon_id] = r.total_pnl
                    
            # 7. Fetch last 30 days payment count and billing
            payment_counts_map = {}
            payment_billing_map = {}
            if salon_ids:
                pay_date = datetime.utcnow() - timedelta(days=30)
                pay_q = text("""
                    SELECT salon_id, COUNT(*) AS pay_count, SUM(total_price) AS total_billing 
                    FROM salonsurf_pro_payments 
                    WHERE created_at >= :pay_date 
                      AND deleted_at IS NULL 
                      AND salon_id IN :salon_ids
                    GROUP BY salon_id
                """)
                pay_res = await conn.execute(pay_q, {"pay_date": pay_date.strftime("%Y-%m-%d 00:00:00"), "salon_ids": salon_ids})
                for r in pay_res.fetchall():
                    payment_counts_map[r.salon_id] = r.pay_count
                    payment_billing_map[r.salon_id] = r.total_billing
                    
            # 8. Fetch outlet counts per head
            head_outlets_count = {}
            if head_ids:
                out_q = text("""
                    SELECT salon_head_id, COUNT(*) AS cnt 
                    FROM salons 
                    WHERE deleted_at IS NULL 
                      AND salon_head_id IN :head_ids 
                    GROUP BY salon_head_id
                """)
                out_res = await conn.execute(out_q, {"head_ids": head_ids})
                for r in out_res.fetchall():
                    head_outlets_count[r.salon_head_id] = r.cnt

            # Open CSV writer
            writer = cls.get_csv_writer(output_file, headers, **kwargs)
            writer.writerow(headers)

            gc.disable()
            try:
                processed_count = 0
                chunk_size = 1000
                for i in range(0, len(rows), chunk_size):
                    chunk = rows[i:i + chunk_size]
                    rows_to_write = []
                    for row in chunk:
                        # Replicate the day/validity logic from Laravel
                        valid_days = set(validities.get(row.offer_id, []))
                        week = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                        weekdays = {'Monday', 'Tuesday', 'Wednesday', 'Thursday'}
                        weekends = {'Friday', 'Saturday', 'Sunday'}

                        weekdays_offer = True
                        weekend_offer = True
                        every_day_offer = True

                        for day in week:
                            is_valid = day in valid_days
                            if day in weekdays and not is_valid:
                                weekdays_offer = False
                            if day in weekends and not is_valid:
                                weekend_offer = False
                            if not is_valid:
                                every_day_offer = False

                        if every_day_offer or (weekdays_offer and weekend_offer):
                            weekdays_offer = False
                            weekend_offer = False
                            every_day_offer = True

                        # Replicate Subtype logic
                        subtype = None
                        min_pay = row.min_payments if row.min_payments is not None else 0
                        max_pay = row.max_payments if row.max_payments is not None else 0
                        used_by_all = (min_pay == 0 and max_pay == 9999)

                        if row.offer_type == "general":
                            if row.usable_once and every_day_offer and min_pay == 0:
                                subtype = "First Time Offer"
                            elif every_day_offer and min_pay == 2 and max_pay == 5:
                                subtype = "2nd to 5th time Offer"
                            elif every_day_offer and min_pay == 5 and max_pay > 5:
                                subtype = "5+ time Offer"
                            elif weekdays_offer:
                                subtype = "Weekdays Offer"
                            elif weekend_offer:
                                subtype = "Weekend Offer"
                        else:
                            subtype = row.offer_type

                        if subtype and used_by_all:
                            subtype += " (All Customers)"

                        # Replicate values logic
                        is_first_time = (subtype == 'First Time Offer')
                        is_weekday = (subtype is not None and 'Weekdays Offer' in subtype)
                        is_weekend = (subtype is not None and 'Weekend Offer' in subtype)

                        first_time_discount = row.discount_percentage if is_first_time else ""
                        first_time_cashback = row.cashback_percentage if is_first_time else ""

                        weekday_discount = row.discount_percentage if is_weekday else ""
                        weekday_cashback = row.cashback_percentage if is_weekday else ""

                        weekend_discount = row.discount_percentage if is_weekend else ""
                        weekend_cashback = row.cashback_percentage if is_weekend else ""

                        # Margin
                        margin = ""
                        if not row.is_commissionable:
                            margin_val = latest_margins_map.get(row.salon_id)
                            if margin_val is not None:
                                margin = float(margin_val)

                        # Enabled label
                        is_enabled = "No" if row.is_disabled else "Yes"

                        # Performance and metrics
                        pay_cnt = payment_counts_map.get(row.salon_id, 0)
                        
                        billing_val = payment_billing_map.get(row.salon_id)
                        billing = float(billing_val) if billing_val is not None else 0.0

                        metric = metrics_map.get(row.salon_id, {})
                        comp_val = metric.get("completion_rate")
                        completion_rate = float(comp_val) if comp_val is not None else 0.0
                        
                        last_month_appts = int(metric.get("total_appointments")) if metric.get("total_appointments") is not None else 0

                        # Head balance and outlets
                        bal_val = balances_map.get(row.salon_head_id)
                        current_balance = float(bal_val) if bal_val is not None else 0.0
                        
                        outlet_count = int(head_outlets_count.get(row.salon_head_id)) if head_outlets_count.get(row.salon_head_id) is not None else 0

                        # PnL
                        pnl_val = pnl_map.get(row.salon_id)
                        last_30_days_pnl = float(pnl_val) if pnl_val is not None else 0.0

                        # Growth Manager
                        growth_manager = rm_map.get(row.salon_id, "")

                        # Format last updated
                        updated_str = ""
                        if row.offer_updated_at:
                            dt = row.offer_updated_at
                            updated_str = f"{dt.day} {dt.strftime('%B %Y')}"

                        rows_to_write.append([
                            row.salon_id,
                            first_time_discount,
                            first_time_cashback,
                            weekday_discount,
                            weekday_cashback,
                            weekend_discount,
                            weekend_cashback,
                            row.head_title or "",
                            row.salon_name or "",
                            row.salon_location or "",
                            row.city or "",
                            row.pincode or "",
                            row.salon_area or "",
                            margin,
                            is_enabled,
                            row.offer_type or "",
                            pay_cnt,
                            billing,
                            completion_rate,
                            last_month_appts,
                            current_balance,
                            outlet_count,
                            last_30_days_pnl,
                            growth_manager,
                            updated_str
                        ])

                    writer.writerows(rows_to_write)
                    processed_count += len(chunk)
                    if progress_callback:
                        await progress_callback(processed_count)
            finally:
                gc.enable()
