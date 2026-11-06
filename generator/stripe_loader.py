"""Loads the synthetic billing data into a Stripe account in TEST mode.

Per billed company: customer -> (per invoice) draft invoice -> invoice item
-> finalize -> pay in full / partial payment / leave unpaid -> refund.

Design choices (see docs/decisions/0001-synthetic-data.md):
- Plain REST calls with `requests`, API version pinned in a header, so the
  behaviour does not change when Stripe releases a new version.
- Every create call sends an Idempotency-Key derived from our external id:
  re-running the loader never charges or creates anything twice.
- Stripe stamps objects with the real creation time, so the simulated
  business dates travel in metadata (invoice_date, due_date, paid_at).
- A partial payment is a separate PaymentIntent that references the invoice
  in metadata; the invoice itself stays open, as happens in real life when
  a customer wires part of the amount.
"""

from __future__ import annotations

import logging

from generator.http import RateLimitedClient
from generator.model import Dataset
from generator.state import LoadState

log = logging.getLogger(__name__)

STRIPE_API_VERSION = "2024-06-20"
TEST_CARD = "pm_card_visa"  # Stripe's built-in test payment method


def _form(data: dict, prefix: str = "") -> dict[str, str]:
    """Flatten nested dicts/lists into Stripe's form encoding: metadata[key]=value."""
    out: dict[str, str] = {}
    for key, value in data.items():
        full = f"{prefix}[{key}]" if prefix else key
        if isinstance(value, dict):
            out.update(_form(value, full))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                out[f"{full}[{i}]"] = str(item)
        elif value is not None:
            out[full] = str(value).lower() if isinstance(value, bool) else str(value)
    return out


def _cents(amount: float) -> int:
    return int(round(amount * 100))


class StripeLoader:
    def __init__(self, api_key: str, state: LoadState, config: dict, client: RateLimitedClient | None = None):
        if not api_key.startswith(("sk_test_", "rk_test_")):
            raise ValueError("Refusing to run: STRIPE_TEST_KEY must be a TEST mode key (sk_test_...)")
        self.state = state
        self.currency = config.get("currency", "usd")
        self.client = client or RateLimitedClient(
            "https://api.stripe.com",
            {"Authorization": f"Bearer {api_key}", "Stripe-Version": STRIPE_API_VERSION},
            min_interval=0.08,
        )

    def _post(self, path: str, data: dict, idem_key: str | None = None) -> dict:
        headers = {"Idempotency-Key": idem_key} if idem_key else {}
        return self.client.request("POST", path, data=_form(data), headers=headers)

    # ------------------------------------------------------------------ #
    def load(self, ds: Dataset) -> None:
        payments_by_invoice = {p.invoice_id: p for p in ds.payments}
        invoices_by_company: dict[str, list] = {}
        for inv in ds.invoices:
            invoices_by_company.setdefault(inv.crm_company_id, []).append(inv)

        for cust in ds.customers:
            cus_id = self._customer(cust)
            pm_id = None
            for inv in invoices_by_company.get(cust.crm_company_id, []):
                if self.state.has("invoice", inv.external_id):
                    continue
                pay = payments_by_invoice.get(inv.external_id)
                if pay and pm_id is None:
                    pm_id = self._payment_method(cust.crm_company_id, cus_id)
                self._invoice(inv, cus_id, pay, pm_id)
                self.state.save()  # one invoice fully processed = one checkpoint
        log.info("Stripe load finished with %d API calls", self.client.calls)

    def _customer(self, cust) -> str:
        key = cust.crm_company_id
        if self.state.has("customer", key):
            return self.state.get("customer", key)
        metadata = {"crm_company_id": cust.external_id} if cust.external_id else {}
        resp = self._post("/v1/customers",
                          {"name": cust.name, "email": cust.email, "metadata": metadata},
                          idem_key=f"customer-{key}")
        self.state.set("customer", key, resp["id"])
        self.state.save()
        return resp["id"]

    def _payment_method(self, company_id: str, cus_id: str) -> str:
        if self.state.has("payment_method", company_id):
            return self.state.get("payment_method", company_id)
        resp = self._post(f"/v1/payment_methods/{TEST_CARD}/attach", {"customer": cus_id},
                          idem_key=f"pm-{company_id}")
        self.state.set("payment_method", company_id, resp["id"])
        return resp["id"]

    def _invoice(self, inv, cus_id: str, pay, pm_id: str | None) -> None:
        meta = {"invoice_external_id": inv.external_id,
                "invoice_date": inv.invoice_date.isoformat(), "due_date": inv.due_date.isoformat()}
        if inv.deal_ref:
            meta["crm_deal_id"] = inv.deal_ref
        draft = self._post("/v1/invoices", {
            "customer": cus_id, "collection_method": "send_invoice", "days_until_due": 30,
            "auto_advance": False, "currency": self.currency, "metadata": meta,
        }, idem_key=f"invoice-{inv.external_id}")
        self._post("/v1/invoiceitems", {
            "customer": cus_id, "invoice": draft["id"], "amount": _cents(inv.amount),
            "currency": self.currency, "description": inv.product,
        }, idem_key=f"item-{inv.external_id}")
        final = self._post(f"/v1/invoices/{draft['id']}/finalize", {},
                           idem_key=f"finalize-{inv.external_id}")
        self.state.set("invoice", inv.external_id, final["id"])

        if not pay:
            return  # unpaid (or not yet due): invoice stays open
        pay_meta = {"payment_external_id": pay.external_id, "paid_at": pay.paid_at.isoformat()}
        if pay.kind == "full":
            paid = self._post(f"/v1/invoices/{final['id']}/pay", {"payment_method": pm_id},
                              idem_key=f"pay-{pay.external_id}")
            pi_id = paid.get("payment_intent")
            if pi_id:  # tag the payment with its simulated business date
                self._post(f"/v1/payment_intents/{pi_id}", {"metadata": pay_meta})
        else:
            pi = self._post("/v1/payment_intents", {
                "amount": _cents(pay.amount), "currency": self.currency, "customer": cus_id,
                "payment_method": pm_id, "payment_method_types": ["card"], "confirm": True,
                "description": f"Partial payment for {inv.external_id}",
                "metadata": {**pay_meta, "invoice_external_id": inv.external_id},
            }, idem_key=f"partial-{pay.external_id}")
            pi_id = pi["id"]
        self.state.set("payment", pay.external_id, pi_id or "")

        if pay.refunded_at and pi_id:
            self._post("/v1/refunds", {
                "payment_intent": pi_id,
                "metadata": {"refunded_at": pay.refunded_at.isoformat(), "payment_external_id": pay.external_id},
            }, idem_key=f"refund-{pay.external_id}")
