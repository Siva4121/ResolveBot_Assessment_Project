
import sqlite3
import json
import uuid

from datetime import date, datetime, time
from dateutil.relativedelta import relativedelta


class ShopTools:
    def __init__(self, db_path, app_today):
        self.db_path = db_path
        self.today = date.fromisoformat(app_today)

    def connect(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def param(self, con, key, default=None):
        row = con.execute(
            "SELECT value FROM policy_parameters WHERE key=?",
            (key,)
        ).fetchone()

        return int(row["value"]) if row else default

    def owned_order(self, con, customer_id, order_id):
        return con.execute(
            "SELECT * FROM orders WHERE order_id=? AND customer_id=?",
            (order_id, customer_id)
        ).fetchone()

    def get_orders(self, customer_id, order_id=None, status=None):
        with self.connect() as con:
            sql = "SELECT * FROM orders WHERE customer_id=?"
            args = [customer_id]

            if order_id:
                row = self.owned_order(con, customer_id, order_id)

                if not row:
                    return {
                        "error_code": "ORDER_NOT_FOUND",
                        "message": "I couldn't find that order on your account."
                    }

                sql += " AND order_id=?"
                args.append(order_id)

            if status:
                sql += " AND status=?"
                args.append(status)

            orders = []

            rows = con.execute(
                sql + " ORDER BY order_date DESC",
                args
            ).fetchall()

            for order_row in rows:
                shipment = con.execute(
                    "SELECT * FROM shipments WHERE order_id=?",
                    (order_row["order_id"],)
                ).fetchone()

                delivered_at = (
                    shipment["delivered_at"]
                    if shipment and shipment["delivered_at"]
                    else None
                )

                delivered_date = (
                    date.fromisoformat(delivered_at[:10])
                    if delivered_at else None
                )

                days_since_delivery = (
                    (self.today - delivered_date).days
                    if delivered_date else None
                )

                items = []

                item_rows = con.execute(
                    """
                    SELECT oi.*, p.name, p.returnable, p.warranty_class
                    FROM order_items oi
                    JOIN products p ON p.product_id=oi.product_id
                    WHERE oi.order_id=?
                    """,
                    (order_row["order_id"],)
                ).fetchall()

                for item_row in item_rows:
                    months = {
                        "standard": self.param(
                            con, "standard_warranty_months", 12
                        ),
                        "extended": self.param(
                            con, "extended_warranty_months", 24
                        ),
                        "none": 0
                    }.get(item_row["warranty_class"], 0)

                    warranty_end = (
                        delivered_date + relativedelta(months=months)
                        if delivered_date and months else None
                    )

                    items.append({
                        "item_id": item_row["item_id"],
                        "product_id": item_row["product_id"],
                        "name": item_row["name"],
                        "qty": item_row["qty"],
                        "opened": bool(item_row["opened"]),
                        "returnable": item_row["returnable"],
                        "warranty_class": item_row["warranty_class"],
                        "warranty_end_date": (
                            warranty_end.isoformat()
                            if warranty_end else None
                        ),
                        "warranty_active": bool(
                            warranty_end and self.today <= warranty_end
                        )
                    })

                orders.append({
                    "order_id": order_row["order_id"],
                    "order_date": order_row["order_date"],
                    "status": order_row["status"],
                    "total": order_row["total"],
                    "carrier": shipment["carrier"] if shipment else None,
                    "shipment_status": (
                        shipment["status"] if shipment else None
                    ),
                    "delivery_date": (
                        delivered_date.isoformat()
                        if delivered_date else None
                    ),
                    # Keep the original timestamp for the 48-hour rule.
                    "delivered_at": delivered_at,
                    "days_since_delivery": days_since_delivery,
                    "eta": shipment["eta"] if shipment else None,
                    "items": items
                })

            return {"orders": orders}

    def check_return_eligibility(
        self, customer_id, order_id, item_ids, reason
    ):
        allowed_reasons = {
            "changed_mind",
            "defective",
            "damaged_on_arrival"
        }

        if reason not in allowed_reasons:
            return {
                "error_code": "INVALID_REASON",
                "message": "Invalid return reason."
            }

        with self.connect() as con:
            order = self.owned_order(con, customer_id, order_id)

            if not order:
                return {
                    "error_code": "ORDER_NOT_FOUND",
                    "message": "I couldn't find that order on your account."
                }

            shipment = con.execute(
                "SELECT delivered_at FROM shipments WHERE order_id=?",
                (order_id,)
            ).fetchone()

            if not shipment or not shipment["delivered_at"]:
                return {
                    "error_code": "NOT_DELIVERED",
                    "message": "This order has not been delivered yet."
                }

            delivered_at = shipment["delivered_at"]
            delivered_date = date.fromisoformat(delivered_at[:10])
            days = (self.today - delivered_date).days

            return_window = self.param(
                con, "return_window_days", 30
            )

            effective_reason = reason
            damage_report_note = None

            if reason == "damaged_on_arrival":
                damage_window_hours = self.param(
                    con, "damaged_report_window_hours", 48
                )

                # The fixed APP_TODAY is used as the reference date.
                # Use end-of-day so the result is deterministic.
                reference_time = datetime.combine(
                    self.today, time.max
                )

                try:
                    delivery_time = datetime.fromisoformat(
                        delivered_at.replace("Z", "+00:00")
                    )

                    # Compare local-naive timestamps consistently.
                    if delivery_time.tzinfo is not None:
                        delivery_time = delivery_time.replace(tzinfo=None)

                    elapsed_hours = (
                        reference_time - delivery_time
                    ).total_seconds() / 3600

                    if elapsed_hours > damage_window_hours:
                        # Late damage-on-arrival reports are handled as
                        # defective-item reports under the supplied policy.
                        effective_reason = "defective"
                        damage_report_note = (
                            "The 48-hour damaged-on-arrival reporting "
                            "period has passed; this is being handled "
                            "as a defective-item report."
                        )

                except (ValueError, TypeError):
                    return {
                        "error_code": "INVALID_DELIVERY_TIMESTAMP",
                        "message": (
                            "The delivery timestamp could not be read "
                            "to check the damaged-item reporting period."
                        )
                    }

            for item_id in item_ids:
                item = con.execute(
                    """
                    SELECT oi.*, p.name, p.returnable
                    FROM order_items oi
                    JOIN products p ON p.product_id=oi.product_id
                    WHERE oi.order_id=? AND oi.item_id=?
                    """,
                    (order_id, item_id)
                ).fetchone()

                if not item:
                    return {
                        "error_code": "INVALID_ITEM",
                        "message": f"Item {item_id} is not in this order."
                    }

                if item["returnable"] == "no":
                    return {
                        "error_code": "NON_RETURNABLE",
                        "message": f"{item['name']} cannot be returned."
                    }

                if days > return_window:
                    return {
                        "error_code": "RETURN_WINDOW_EXPIRED",
                        "message": (
                            f"The {return_window}-day return window "
                            "has expired."
                        )
                    }

                if (
                    item["opened"]
                    and effective_reason == "changed_mind"
                    and item["returnable"] == "unopened_only"
                ):
                    return {
                        "error_code": "OPENED_NOT_RETURNABLE",
                        "message": (
                            f"Opened {item['name']} cannot be returned "
                            "for a change of mind."
                        )
                    }

            result = {
                "eligible": True,
                "days_since_delivery": days,
                "return_window_days": return_window,
                "effective_reason": effective_reason
            }

            if damage_report_note:
                result["note"] = damage_report_note

            return result

    def create_return_request(
        self, customer_id, order_id, item_ids, reason
    ):
        check = self.check_return_eligibility(
            customer_id, order_id, item_ids, reason
        )

        if "error_code" in check:
            return check

        # Store the effective reason returned by the eligibility check.
        effective_reason = check.get("effective_reason", reason)

        with self.connect() as con:
            request_id = str(uuid.uuid4())

            con.execute(
                """
                INSERT INTO return_requests
                (request_id, order_id, customer_id, item_ids,
                 reason, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'requested', ?)
                """,
                (
                    request_id,
                    order_id,
                    customer_id,
                    json.dumps(item_ids),
                    effective_reason,
                    datetime.now().isoformat(timespec="seconds")
                )
            )

            return {
                "request_id": request_id,
                "status": "requested",
                "reason": effective_reason
            }

    def create_support_ticket(
        self, customer_id, order_id, ticket_type, summary,
        item_id=None
    ):
        if ticket_type not in ("warranty", "cancellation"):
            return {
                "error_code": "INVALID_TICKET_TYPE",
                "message": (
                    "Ticket type must be warranty or cancellation."
                )
            }

        with self.connect() as con:
            order = self.owned_order(con, customer_id, order_id)

            if not order:
                return {
                    "error_code": "ORDER_NOT_FOUND",
                    "message": "I couldn't find that order on your account."
                }

            if ticket_type == "cancellation":
                if order["status"] != "processing":
                    return {
                        "error_code": "ORDER_ALREADY_SHIPPED",
                        "message": (
                            "This order can only be cancelled while "
                            "it is processing."
                        )
                    }

            if ticket_type == "warranty":
                if not item_id:
                    return {
                        "error_code": "WARRANTY_ITEM_REQUIRED",
                        "message": (
                            "A specific order item is required "
                            "for a warranty ticket."
                        )
                    }

                info = self.get_orders(customer_id, order_id)

                if "error_code" in info:
                    return info

                order_info = info["orders"][0]

                if order_info["status"] != "delivered":
                    return {
                        "error_code": "ORDER_NOT_DELIVERED",
                        "message": (
                            "Warranty support is available after delivery."
                        )
                    }

                # Check the warranty of the exact item selected.
                selected_item = next(
                    (
                        item for item in order_info["items"]
                        if item["item_id"] == item_id
                    ),
                    None
                )

                if selected_item is None:
                    return {
                        "error_code": "INVALID_ITEM",
                        "message": (
                            "The selected item is not part of this order."
                        )
                    }

                if not selected_item["warranty_active"]:
                    return {
                        "error_code": "WARRANTY_EXPIRED",
                        "message": (
                            f"The warranty for {selected_item['name']} "
                            "has expired."
                        )
                    }

            ticket_id = str(uuid.uuid4())

            con.execute(
                """
                INSERT INTO support_tickets
                (ticket_id, order_id, customer_id, ticket_type,
                 summary, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'open', ?)
                """,
                (
                    ticket_id,
                    order_id,
                    customer_id,
                    ticket_type,
                    summary,
                    datetime.now().isoformat(timespec="seconds")
                )
            )

            return {
                "ticket_id": ticket_id,
                "status": "open"
            }
