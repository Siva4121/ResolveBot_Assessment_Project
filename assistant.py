
import re
import uuid

from policy_search import search_policy
from llm import polish_answer


ORDER_RE = re.compile(r"\bSS-?\d+\b", re.I)

ITEM_STOP_WORDS = {
    "the", "and", "with", "for", "item", "my", "is", "are",
    "was", "were", "not", "working", "broken", "fault", "faulty",
    "defective", "damaged", "wrong", "stopped", "charging",
    "please", "help", "warranty", "order", "under", "has", "have",
    "a", "an", "it", "this", "that", "in", "on"
}


def find_mentioned_item(message, items):
    """Identify one item by the product name mentioned in the message."""
    message_words = set(re.findall(r"[a-z0-9]+", message.lower()))
    matches = []

    for item in items:
        name = item.get("name", "").lower().strip()
        name_words = set(re.findall(r"[a-z0-9]+", name))
        useful_words = name_words - ITEM_STOP_WORDS

        if not useful_words:
            continue

        # Prefer a complete product-name match.
        normalized_message = " ".join(
            re.findall(r"[a-z0-9]+", message.lower())
        )
        normalized_name = " ".join(
            re.findall(r"[a-z0-9]+", name)
        )

        if normalized_name and normalized_name in normalized_message:
            matches.append(item)
            continue

        # Otherwise, match distinctive words from the product name.
        if useful_words.intersection(message_words):
            matches.append(item)

    # Only select an item when the match is unambiguous.
    unique_matches = {
        item["item_id"]: item for item in matches
    }

    if len(unique_matches) == 1:
        return next(iter(unique_matches.values()))

    return None


def handle_message(
    message, customer_id, tools, docs, sessions, session_id
):
    msg = message.strip()
    low = msg.lower()

    state = sessions.setdefault(
        session_id,
        {"customer_id": customer_id, "pending": None}
    )

    if state["customer_id"] != customer_id:
        return None

    calls = []

    # Execute a pending action only after a clear confirmation.
    if state["pending"]:
        proposal = state["pending"]

        if low in {
            "yes", "yes please", "confirm", "go ahead",
            "please do", "yes go ahead", "do it"
        }:
            state["pending"] = None

            if proposal["kind"] == "return":
                result = tools.create_return_request(
                    customer_id,
                    proposal["order_id"],
                    proposal["item_ids"],
                    proposal["reason"]
                )

                calls.append({
                    "name": "create_return_request",
                    "args": {
                        "order_id": proposal["order_id"],
                        "item_ids": proposal["item_ids"],
                        "reason": proposal["reason"]
                    },
                    "status": (
                        "error" if "error_code" in result else "success"
                    )
                })

            else:
                result = tools.create_support_ticket(
                    customer_id,
                    proposal["order_id"],
                    proposal["ticket_type"],
                    proposal["summary"],
                    item_id=proposal.get("item_id")
                )

                args = {
                    "order_id": proposal["order_id"],
                    "ticket_type": proposal["ticket_type"],
                    "summary": proposal["summary"]
                }

                if proposal.get("item_id"):
                    args["item_id"] = proposal["item_id"]

                calls.append({
                    "name": "create_support_ticket",
                    "args": args,
                    "status": (
                        "error" if "error_code" in result else "success"
                    )
                })

            if "error_code" in result:
                answer = result["message"]
            elif proposal["kind"] == "return":
                answer = "Your return request has been created."
            else:
                answer = "Your support ticket has been created."

            return reply(answer, "answer", calls)

        # A message other than yes cancels the old proposal.
        state["pending"] = None

    if any(
        word in low
        for word in ["weather", "write a poem", "capital of",
                     "football score"]
    ):
        return reply(
            "I can help with ShopSphere orders, returns, warranties, "
            "cancellations, and store policies.",
            "out_of_scope",
            []
        )

    order_match = ORDER_RE.search(msg)
    order_id = None

    if order_match:
        order_id = order_match.group(0).upper()
        if not order_id.startswith("SS-"):
            order_id = "SS-" + order_id[2:]

    # General policy questions.
    if any(
        word in low
        for word in [
            "policy", "how many days", "return window",
            "warranty period", "shipping fee", "refund"
        ]
    ):
        results = search_policy(msg, docs)

        if not results:
            return reply(
                "The current policies do not cover that question. "
                "Please contact the ShopSphere support team.",
                "no_answer",
                []
            )

        top = results[:3]
        answer = " ".join(
            re.sub(r"\s+", " ", result["text"])
            for result in top
        )
        citations = [
            {
                "doc_id": result["doc_id"],
                "section": result["section"]
            }
            for result in top
        ]

        return reply(
            answer,
            "answer",
            [{
                "name": "search_policy",
                "args": {"query": msg},
                "status": "success"
            }],
            citations=citations
        )

    # Order tracking.
    if any(
        word in low
        for word in [
            "where is", "track", "tracking",
            "delivery status", "when will"
        ]
    ):
        if not order_id:
            return reply(
                "Which order would you like me to track? "
                "Please provide the order ID, for example SS-10458.",
                "clarify",
                []
            )

        result = tools.get_orders(customer_id, order_id)
        calls.append({
            "name": "get_orders",
            "args": {"order_id": order_id},
            "status": (
                "error" if "error_code" in result else "success"
            )
        })

        if "error_code" in result:
            return reply(
                "I couldn't find that order on your account.",
                "no_answer",
                calls
            )

        order = result["orders"][0]
        delivery = (
            f" Expected delivery: {order['eta']}."
            if order.get("eta") else ""
        )

        return reply(
            f"Order {order_id} is {order['status']}.{delivery}",
            "answer",
            calls
        )

    # Return requests and eligibility questions.
    if any(word in low for word in ["return", "send back"]):
        if not order_id:
            return reply(
                "Please provide the order ID so I can check the item, "
                "for example SS-10458.",
                "clarify",
                []
            )

        result = tools.get_orders(customer_id, order_id)
        calls.append({
            "name": "get_orders",
            "args": {"order_id": order_id},
            "status": (
                "error" if "error_code" in result else "success"
            )
        })

        if "error_code" in result:
            return reply(
                "I couldn't find that order on your account.",
                "no_answer",
                calls
            )

        order = result["orders"][0]
        item = find_mentioned_item(msg, order["items"])

        if item is None:
            return reply(
                "Which item would you like to return? Items in this "
                "order: " + ", ".join(
                    f"{i['name']} ({i['item_id']})"
                    for i in order["items"]
                ),
                "clarify",
                calls
            )

        if "damaged on arrival" in low:
            reason = "damaged_on_arrival"
        elif any(
            word in low
            for word in ["defective", "broken", "damaged", "wrong item"]
        ):
            reason = "defective"
        else:
            reason = "changed_mind"

        check = tools.check_return_eligibility(
            customer_id,
            order_id,
            [item["item_id"]],
            reason
        )

        calls.append({
            "name": "check_return_eligibility",
            "args": {
                "order_id": order_id,
                "item_ids": [item["item_id"]],
                "reason": reason
            },
            "status": (
                "error" if "error_code" in check else "success"
            )
        })

        if "error_code" in check:
            return reply(check["message"], "answer", calls)

        # The tool may reclassify a late damage-on-arrival report
        # as a normal defective-item report.
        reason = check.get("effective_reason", reason)

        policy_results = search_policy(
            "return window returnable item",
            docs
        )
        citations = [
            {
                "doc_id": result["doc_id"],
                "section": result["section"]
            }
            for result in policy_results[:2]
        ]

        calls.append({
            "name": "search_policy",
            "args": {"query": "return window returnable item"},
            "status": "success" if policy_results else "error"
        })

        question_only = (
            low.rstrip().endswith("?")
            or low.startswith((
                "can i ", "could i ", "may i ",
                "am i able to ", "is it possible"
            ))
            or "eligible for return" in low
        ) and not low.startswith((
            "i want to return", "please return",
            "return the", "return my", "send back"
        ))

        if question_only:
            return reply(
                f"{item['name']} is eligible for return. "
                "Would you like me to create a return request?",
                "answer",
                calls,
                citations=citations
            )

        state["pending"] = {
            "kind": "return",
            "order_id": order_id,
            "item_ids": [item["item_id"]],
            "reason": reason
        }

        calls.append({
            "name": "create_return_request",
            "args": {
                "order_id": order_id,
                "item_ids": [item["item_id"]],
                "reason": reason
            },
            "status": "pending_confirmation"
        })

        return reply(
            f"{item['name']} is eligible for return. "
            "Shall I create the return request?",
            "answer",
            calls,
            citations=citations,
            pending=True
        )

    # Order cancellation.
    if any(word in low for word in ["cancel", "cancellation"]):
        if not order_id:
            return reply(
                "Please provide the order ID you want to cancel.",
                "clarify",
                []
            )

        result = tools.get_orders(customer_id, order_id)
        calls.append({
            "name": "get_orders",
            "args": {"order_id": order_id},
            "status": (
                "error" if "error_code" in result else "success"
            )
        })

        if "error_code" in result:
            return reply(
                "I couldn't find that order on your account.",
                "no_answer",
                calls
            )

        if result["orders"][0]["status"] != "processing":
            return reply(
                "This order can only be cancelled while it is "
                "processing; it may already have shipped.",
                "answer",
                calls
            )

        state["pending"] = {
            "kind": "ticket",
            "order_id": order_id,
            "ticket_type": "cancellation",
            "summary": "Customer requested order cancellation"
        }

        calls.append({
            "name": "create_support_ticket",
            "args": {
                "order_id": order_id,
                "ticket_type": "cancellation",
                "summary": state["pending"]["summary"]
            },
            "status": "pending_confirmation"
        })

        return reply(
            f"Order {order_id} is still processing. "
            "Shall I open a cancellation ticket?",
            "answer",
            calls,
            pending=True
        )

    # Warranty support: identify the specific product first.
    if any(
        word in low
        for word in [
            "warranty", "stopped charging",
            "not working", "broken", "fault"
        ]
    ):
        if not order_id:
            return reply(
                "Please provide the order ID so I can check the warranty.",
                "clarify",
                []
            )

        result = tools.get_orders(customer_id, order_id)
        calls.append({
            "name": "get_orders",
            "args": {"order_id": order_id},
            "status": (
                "error" if "error_code" in result else "success"
            )
        })

        if "error_code" in result:
            return reply(
                "I couldn't find that order on your account.",
                "no_answer",
                calls
            )

        order = result["orders"][0]

        if order["status"] != "delivered":
            return reply(
                "Warranty support can be checked after the order "
                "has been delivered.",
                "answer",
                calls
            )

        item = find_mentioned_item(msg, order["items"])

        if item is None:
            return reply(
                "Which item has the problem? Items in this order: "
                + ", ".join(
                    f"{i['name']} ({i['item_id']})"
                    for i in order["items"]
                ),
                "clarify",
                calls
            )

        if not item["warranty_active"]:
            return reply(
                f"The warranty for {item['name']} has expired. "
                "I cannot open a warranty ticket for this item.",
                "answer",
                calls
            )

        summary = (
            f"Warranty issue for item {item['item_id']} "
            f"({item['name']}): {msg}"
        )

        state["pending"] = {
            "kind": "ticket",
            "order_id": order_id,
            "ticket_type": "warranty",
            "summary": summary,
            "item_id": item["item_id"]
        }

        calls.append({
            "name": "create_support_ticket",
            "args": {
                "order_id": order_id,
                "ticket_type": "warranty",
                "summary": summary,
                "item_id": item["item_id"]
            },
            "status": "pending_confirmation"
        })

        return reply(
            f"The warranty for {item['name']} is active. "
            "Shall I open a warranty support ticket?",
            "answer",
            calls,
            pending=True
        )

    # A message containing only an order ID.
    if order_id:
        result = tools.get_orders(customer_id, order_id)
        calls.append({
            "name": "get_orders",
            "args": {"order_id": order_id},
            "status": (
                "error" if "error_code" in result else "success"
            )
        })

        if "error_code" in result:
            return reply(
                "I couldn't find that order on your account.",
                "no_answer",
                calls
            )

        return reply(
            "I found your order. Would you like tracking, return, "
            "cancellation, or warranty help?",
            "clarify",
            calls
        )

    return reply(
        "I can help with ShopSphere orders, returns, warranties, "
        "cancellations, and store policies. What would you like to do?",
        "clarify",
        []
    )


def reply(answer, route, calls, citations=None, pending=False):
    # The LLM only polishes wording; it does not control business rules.
    if route == "answer" and not pending:
        answer = polish_answer(answer)

    return {
        "request_id": str(uuid.uuid4()),
        "answer": answer,
        "route": route,
        "citations": citations or [],
        "tool_calls": calls,
        "pending_confirmation": pending
    }
