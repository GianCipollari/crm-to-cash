"""Daily activity: keeps the fictional company alive after the initial seed.

Each simulated day:
  1. HubSpot: a few new contacts and deals; some open deals move one stage
     (and from "contract sent" they close as won or lost).
  2. Stripe: deals won since the seed get invoiced after a short lag;
     open invoices get paid around their due date.

Design (see docs/decisions/0002-daily-activity.md):
- Stateless: it reads what it needs from the APIs, so it can run anywhere,
  including a fresh GitHub Actions runner with no local files.
- Deterministic and idempotent per day: every decision comes from a seeded
  RNG or a stable hash of (record id, day). Running the same day twice
  changes nothing the second time.
- Clean: daily activity plants no new anomalies, so the seed's anomaly
  manifest stays the ground truth. Planted unpaid / partial invoices are
  never paid by this module.
"""

from __future__ import annotations

import hashlib
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from generator import catalog
from generator.http import ApiError, RateLimitedClient
from generator.hubspot_loader import (
    ASSOC_CONTACT_TO_COMPANY, ASSOC_DEAL_TO_COMPANY, ASSOC_DEAL_TO_CONTACT, _assoc, _ms,
)
from generator.model import LOST, OPEN_STAGES, WON, Invoice, _amount, _slug, build_dataset
from generator.stripe_loader import STRIPE_API_VERSION, StripeLoader, _form
from generator.state import LoadState

log = logging.getLogger(__name__)

MOVE_PROBABILITY = 0.03     # chance that an open deal moves on a given day (~5 moves per day)
WIN_PROBABILITY = 0.40      # chance that a deal in "contract sent" closes as won
INVOICE_WINDOW_DAYS = 30    # look back this far for won deals still to invoice


# --------------------------------------------------------------------------- #
# Pure helpers (unit tested without any API)
# --------------------------------------------------------------------------- #
def stable_fraction(*parts: object) -> float:
    """A number in [0, 1) that depends only on its inputs, on every machine."""
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return int(digest[:12], 16) / 16 ** 12


def stable_int(lo: int, hi: int, *parts: object) -> int:
    return lo + int(stable_fraction(*parts) * (hi - lo + 1))


def from_ms(value: str | int | None) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, str) and not value.isdigit():  # ISO string from the API
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date()


@dataclass
class NewContact:
    external_id: str
    company_id: str
    first_name: str
    last_name: str
    email: str
    lead_source: str


@dataclass
class NewDeal:
    external_id: str
    contact_id: str
    company_id: str
    owner: str
    product: str
    amount: float


def plan_new_records(config: dict, day: date, companies: list) -> tuple[list[NewContact], list[NewDeal]]:
    """New contacts and deals for one day. Same inputs, same plan."""
    rng = random.Random(f"{config['seed']}-daily-{day.isoformat()}")
    tag = day.strftime("%Y%m%d")
    sources = config["lead_sources"]
    keys = list(sources)
    contacts = []
    for i in range(1, rng.randint(2, 5) + 1):
        company = rng.choice(companies)
        first, last = rng.choice(catalog.FIRST_NAMES), rng.choice(catalog.LAST_NAMES)
        contacts.append(NewContact(
            external_id=f"CON-D{tag}-{i:02d}",
            company_id=company.external_id,
            first_name=first,
            last_name=last,
            email=f"{_slug(first)}.{_slug(last)}.{tag}{i:02d}@{company.domain}",
            lead_source=rng.choices(keys, [sources[k]["share"] for k in keys])[0],
        ))
    deals = []
    for i, contact in enumerate(rng.sample(contacts, rng.randint(1, min(3, len(contacts)))), start=1):
        deals.append(NewDeal(
            external_id=f"DEAL-D{tag}-{i:02d}",
            contact_id=contact.external_id,
            company_id=contact.company_id,
            owner=rng.choice(config["owners"]),
            product=rng.choice(catalog.PRODUCTS),
            amount=_amount(rng, config["deals"]),
        ))
    return contacts, deals


def next_stage(deal_id: str, stage: str, day: date) -> str:
    """One step forward in the pipeline; from contract sent it closes."""
    if stage == OPEN_STAGES[-1]:
        return WON if stable_fraction(deal_id, day, "outcome") < WIN_PROBABILITY else LOST
    return OPEN_STAGES[OPEN_STAGES.index(stage) + 1]


def should_move(deal_id: str, day: date) -> bool:
    return stable_fraction(deal_id, day, "move") < MOVE_PROBABILITY


def invoice_date_for(deal_id: str, close: date, config: dict) -> date:
    return close + timedelta(days=stable_int(*config["deals"]["invoice_lag_days"], deal_id, "lag"))


def payment_date_for(invoice_id: str, invoice_day: date, due: date, config: dict) -> date:
    delay = stable_int(*config["deals"]["payment_delay_days"], invoice_id, "pay")
    return max(due + timedelta(days=delay), invoice_day)


def planted_open_invoices(config: dict) -> set[str]:
    """Seed invoices that must stay open forever: the planted unpaid and partial ones."""
    ds = build_dataset(config)
    deals = {a.external_id for a in ds.anomalies if a.anomaly_type in ("unpaid_invoice", "partial_payment")}
    return {i.external_id for i in ds.invoices if i.true_deal_id in deals}


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
class DailyRunner:
    def __init__(self, config: dict, hubspot: RateLimitedClient, stripe: RateLimitedClient,
                 stripe_loader: StripeLoader):
        self.config = config
        self.hs = hubspot
        self.st = stripe
        self.stripe_loader = stripe_loader
        self.seed = build_dataset(config)
        self.seed_end = date.fromisoformat(config["as_of_date"])
        self.keep_open = planted_open_invoices(config)
        self.summary: dict[str, int] = {}

    @classmethod
    def from_keys(cls, config: dict, hubspot_token: str, stripe_key: str, state_path) -> "DailyRunner":
        hs = RateLimitedClient("https://api.hubapi.com",
                               {"Authorization": f"Bearer {hubspot_token}", "Content-Type": "application/json"},
                               min_interval=0.25)  # search endpoints allow fewer calls per second
        st = RateLimitedClient("https://api.stripe.com",
                               {"Authorization": f"Bearer {stripe_key}", "Stripe-Version": STRIPE_API_VERSION},
                               min_interval=0.08)
        loader = StripeLoader(stripe_key, LoadState(state_path), config, client=st)
        return cls(config, hs, st, loader)

    def _count(self, key: str, n: int = 1) -> None:
        self.summary[key] = self.summary.get(key, 0) + n

    # ---------------- HubSpot helpers ---------------- #
    def _read_by_external_id(self, obj: str, ids: list[str], props: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        resp = self.hs.request("POST", f"/crm/v3/objects/{obj}/batch/read", json={
            "idProperty": "external_id", "properties": props, "inputs": [{"id": i} for i in ids]})
        return {r["properties"]["external_id"]: r for r in resp.get("results", [])}

    def _search_deals(self, filters: list[dict], props: list[str]) -> list[dict]:
        results, after = [], None
        while True:
            body = {"filterGroups": [{"filters": filters}], "properties": props, "limit": 100,
                    "sorts": [{"propertyName": "hs_object_id", "direction": "ASCENDING"}]}
            if after:
                body["after"] = after
            resp = self.hs.request("POST", "/crm/v3/objects/deals/search", json=body)
            results.extend(resp.get("results", []))
            after = resp.get("paging", {}).get("next", {}).get("after")
            if not after:
                return results

    def ensure_daily_property(self) -> None:
        try:
            self.hs.request("POST", "/crm/v3/properties/deals", json={
                "name": "sim_last_moved", "label": "Simulation: last stage move",
                "type": "date", "fieldType": "date", "groupName": "dealinformation"})
        except ApiError as err:
            if err.status != 409:
                raise

    # ---------------- Step 1: new contacts and deals ---------------- #
    def create_new_records(self, day: date) -> None:
        contacts, deals = plan_new_records(self.config, day, self.seed.companies)
        companies = self._read_by_external_id(
            "companies", sorted({c.company_id for c in contacts}), ["external_id"])
        existing = self._read_by_external_id("contacts", [c.external_id for c in contacts], ["external_id"])
        to_create = [c for c in contacts if c.external_id not in existing and c.company_id in companies]
        if to_create:
            resp = self.hs.request("POST", "/crm/v3/objects/contacts/batch/create", json={"inputs": [{
                "properties": {"external_id": c.external_id, "firstname": c.first_name, "lastname": c.last_name,
                               "email": c.email, "lead_source": c.lead_source,
                               "source_created_date": _ms(day)},
                "associations": [_assoc(companies[c.company_id]["id"], ASSOC_CONTACT_TO_COMPANY)],
            } for c in to_create]})
            for r in resp.get("results", []):
                existing[r["properties"]["external_id"]] = r
            self._count("contacts_created", len(to_create))

        existing_deals = self._read_by_external_id("deals", [d.external_id for d in deals], ["external_id"])
        new_deals = [d for d in deals if d.external_id not in existing_deals and d.contact_id in existing]
        if new_deals:
            self.hs.request("POST", "/crm/v3/objects/deals/batch/create", json={"inputs": [{
                "properties": {"external_id": d.external_id, "dealname": f"{d.product} - {d.company_id}",
                               "amount": f"{d.amount:.2f}", "pipeline": "default",
                               "dealstage": OPEN_STAGES[0], "sales_rep": d.owner.lower().replace(" ", "_"),
                               "deal_created_date": _ms(day)},
                "associations": [_assoc(companies[d.company_id]["id"], ASSOC_DEAL_TO_COMPANY),
                                 _assoc(existing[d.contact_id]["id"], ASSOC_DEAL_TO_CONTACT)],
            } for d in new_deals]})
            self._count("deals_created", len(new_deals))

    # ---------------- Step 2: move open deals ---------------- #
    def move_deals(self, day: date) -> None:
        open_deals = self._search_deals(
            [{"propertyName": "dealstage", "operator": "IN", "values": OPEN_STAGES}],
            ["external_id", "dealstage", "sim_last_moved"])
        updates = []
        for d in open_deals:
            p = d["properties"]
            eid = p.get("external_id")
            if not eid or from_ms(p.get("sim_last_moved")) == day or not should_move(eid, day):
                continue
            stage = next_stage(eid, p["dealstage"], day)
            props = {"dealstage": stage, "sim_last_moved": _ms(day)}
            if stage in (WON, LOST):
                props["closedate"] = _ms(day)
                self._count("deals_won" if stage == WON else "deals_lost")
            else:
                self._count("deals_advanced")
            updates.append({"id": d["id"], "properties": props})
        for i in range(0, len(updates), 100):
            self.hs.request("POST", "/crm/v3/objects/deals/batch/update", json={"inputs": updates[i:i + 100]})

    # ---------------- Step 3: invoice deals won after the seed ---------------- #
    def _stripe_search(self, resource: str, query: str) -> list[dict]:
        return self.st.request("GET", f"/v1/{resource}/search", params={"query": query}).get("data", [])

    def _customer_for(self, company: dict) -> str:
        cid = company["properties"]["external_id"]
        domain = company["properties"].get("domain") or ""
        found = self._stripe_search("customers", f"metadata['crm_company_id']:'{cid}'")
        if not found and domain:  # seed customers planted without the CRM id
            found = self._stripe_search("customers", f"email:'billing@{domain}'")
        if found:
            return found[0]["id"]
        resp = self.st.request("POST", "/v1/customers", data=_form({
            "name": company["properties"].get("name") or cid, "email": f"billing@{domain}",
            "metadata": {"crm_company_id": cid}}), headers={"Idempotency-Key": f"customer-{cid}"})
        self._count("customers_created")
        return resp["id"]

    def invoice_won_deals(self, day: date) -> None:
        start = max(self.seed_end + timedelta(days=1), day - timedelta(days=INVOICE_WINDOW_DAYS))
        won = self._search_deals([
            {"propertyName": "dealstage", "operator": "EQ", "value": WON},
            {"propertyName": "closedate", "operator": "GTE", "value": str(_ms(start))},
        ], ["external_id", "amount", "dealname", "closedate"])
        due_now = []
        for d in won:
            p = d["properties"]
            close = from_ms(p.get("closedate"))
            if p.get("external_id") and close and invoice_date_for(p["external_id"], close, self.config) <= day:
                due_now.append(d)
        if not due_now:
            return
        assoc = self.hs.request("POST", "/crm/v4/associations/deals/companies/batch/read",
                                json={"inputs": [{"id": d["id"]} for d in due_now]})
        company_of = {r["from"]["id"]: str(r["to"][0]["toObjectId"]) for r in assoc.get("results", []) if r.get("to")}
        companies = {}
        ids = sorted(set(company_of.values()))
        if ids:
            resp = self.hs.request("POST", "/crm/v3/objects/companies/batch/read", json={
                "properties": ["external_id", "name", "domain"], "inputs": [{"id": i} for i in ids]})
            companies = {r["id"]: r for r in resp.get("results", [])}

        for d in due_now:
            p = d["properties"]
            eid = p["external_id"]
            company = companies.get(company_of.get(d["id"], ""))
            if not company or self._stripe_search("invoices", f"metadata['crm_deal_id']:'{eid}'"):
                continue
            inv_day = invoice_date_for(eid, from_ms(p["closedate"]), self.config)
            inv = Invoice(
                external_id=f"INV-{eid}", crm_company_id=company["properties"]["external_id"],
                deal_ref=eid, product=(p.get("dealname") or "").split(" - ")[0] or "Contable Cloud",
                amount=float(p.get("amount") or 0), invoice_date=inv_day,
                due_date=inv_day + timedelta(days=self.config["deals"]["payment_terms_days"]),
            )
            self.stripe_loader._invoice(inv, self._customer_for(company), pay=None, pm_id=None)
            self._count("invoices_created")

    # ---------------- Step 4: pay open invoices that are due ---------------- #
    def _open_invoices(self) -> list[dict]:
        out, after = [], None
        while True:
            params = {"status": "open", "limit": 100}
            if after:
                params["starting_after"] = after
            resp = self.st.request("GET", "/v1/invoices", params=params)
            out.extend(resp.get("data", []))
            if not resp.get("has_more"):
                return out
            after = resp["data"][-1]["id"]

    def _payment_method(self, customer: str) -> str:
        found = self.st.request("GET", f"/v1/customers/{customer}/payment_methods",
                                params={"type": "card", "limit": 1}).get("data", [])
        if found:
            return found[0]["id"]
        return self.st.request("POST", "/v1/payment_methods/pm_card_visa/attach",
                               data=_form({"customer": customer}),
                               headers={"Idempotency-Key": f"pm-{customer}"})["id"]

    def pay_due_invoices(self, day: date) -> None:
        for inv in self._open_invoices():
            meta = inv.get("metadata") or {}
            iid = meta.get("invoice_external_id")
            if not iid or iid in self.keep_open or "due_date" not in meta:
                continue
            paid_at = payment_date_for(iid, date.fromisoformat(meta["invoice_date"]),
                                       date.fromisoformat(meta["due_date"]), self.config)
            if paid_at > day:
                continue
            pm = self._payment_method(inv["customer"])
            paid = self.st.request("POST", f"/v1/invoices/{inv['id']}/pay", data=_form({"payment_method": pm}),
                                   headers={"Idempotency-Key": f"pay-{iid}"})
            if paid.get("payment_intent"):
                self.st.request("POST", f"/v1/payment_intents/{paid['payment_intent']}", data=_form({
                    "metadata": {"payment_external_id": f"PAY-{iid}", "paid_at": paid_at.isoformat()}}))
            self._count("invoices_paid")
            log.info("Paid %s (simulated date %s, %.2f)", iid, paid_at, inv.get("amount_due", 0) / 100)

    # ---------------- One day ---------------- #
    def run_day(self, day: date) -> dict[str, int]:
        if day <= self.seed_end:
            raise ValueError(f"Daily activity starts after the seed period ({self.seed_end})")
        self.summary = {}
        self.ensure_daily_property()
        self.create_new_records(day)
        self.move_deals(day)
        self.invoice_won_deals(day)
        self.pay_due_invoices(day)
        self.stripe_loader.state.save()
        log.info("Day %s: %s", day, self.summary or "no changes")
        return dict(self.summary)
