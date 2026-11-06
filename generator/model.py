"""Builds the synthetic dataset in memory.

The build is pure and deterministic: same config + same seed = same dataset.
Nothing here talks to an API, so it can be tested and inspected offline
(see `python -m generator.cli seed --dry-run`).
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import yaml

from generator import catalog
from generator.anomalies import Anomaly, name_variant, strip_accents, weighted_sample

# HubSpot default sales pipeline stage ids, in order.
OPEN_STAGES = [
    "appointmentscheduled",
    "qualifiedtobuy",
    "presentationscheduled",
    "decisionmakerboughtin",
    "contractsent",
]
WON, LOST = "closedwon", "closedlost"


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
@dataclass
class Company:
    external_id: str
    name: str
    domain: str
    industry: str
    country: str
    tax_id: str
    created_at: date


@dataclass
class Contact:
    external_id: str
    company_id: str
    first_name: str
    last_name: str
    email: str
    lead_source: str
    created_at: date


@dataclass
class Deal:
    external_id: str
    company_id: str
    contact_id: str
    owner: str
    product: str
    amount: float
    created_at: date
    close_date: date | None
    stage: str
    duplicate_of: str | None = None


@dataclass
class Customer:
    """A billing customer. `crm_company_id` is the truth; `external_id` is what
    billing actually stored (None when the CRM id was never recorded)."""
    crm_company_id: str
    external_id: str | None
    name: str
    email: str


@dataclass
class Invoice:
    external_id: str
    crm_company_id: str
    deal_ref: str | None  # CRM deal id written on the invoice, None if missing
    product: str
    amount: float
    invoice_date: date
    due_date: date
    true_deal_id: str = ""  # ground truth, never sent to billing


@dataclass
class Payment:
    external_id: str
    invoice_id: str
    amount: float
    paid_at: date
    kind: str                  # full | partial
    refunded_at: date | None = None


@dataclass
class Dataset:
    companies: list[Company] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    deals: list[Deal] = field(default_factory=list)
    customers: list[Customer] = field(default_factory=list)
    invoices: list[Invoice] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", strip_accents(text).lower())


def _random_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, max((end - start).days, 0)))


def _tax_id(rng: random.Random, country: str) -> str:
    if country == "AR":  # CUIT-like format, not a real CUIT
        return f"30-{rng.randint(10_000_000, 99_999_999)}-{rng.randint(0, 9)}"
    return f"{country}{rng.randint(100_000_000, 999_999_999)}"


def _amount(rng: random.Random, cfg: dict) -> float:
    median = cfg["amount_median_usd"]
    value = rng.lognormvariate(mu=0, sigma=0.8) * median
    value = min(max(value, cfg["amount_min_usd"]), cfg["amount_max_usd"])
    return float(round(value / 100) * 100)


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def build_dataset(config: dict) -> Dataset:
    rng = random.Random(config["seed"])
    start = date.fromisoformat(config["start_date"])
    as_of = date.fromisoformat(config["as_of_date"])
    vol = config["volumes"]
    sources = config["lead_sources"]
    dcfg = config["deals"]
    acfg = config["anomalies"]
    ds = Dataset()

    # ---- Companies ------------------------------------------------------- #
    used_names, used_domains = set(), set()
    countries = list(catalog.COUNTRIES)
    cweights = list(catalog.COUNTRIES.values())
    tld = {"AR": ".com.ar", "MX": ".com.mx", "CL": ".cl", "CO": ".com.co", "UY": ".com.uy"}
    for i in range(1, vol["companies"] + 1):
        while True:
            base = f"{rng.choice(catalog.COMPANY_PREFIXES)} {rng.choice(catalog.COMPANY_CORES)}"
            if base not in used_names:
                used_names.add(base)
                break
        country = rng.choices(countries, cweights)[0]
        domain = _slug(base) + tld[country]
        n = 2
        while domain in used_domains:
            domain = f"{_slug(base)}{n}{tld[country]}"
            n += 1
        used_domains.add(domain)
        ds.companies.append(
            Company(
                external_id=f"CMP-{i:04d}",
                name=f"{base} {rng.choice(catalog.LEGAL_FORMS)}",
                domain=domain,
                industry=rng.choice(catalog.INDUSTRIES),
                country=country,
                tax_id=_tax_id(rng, country),
                created_at=_random_date(rng, start, as_of - timedelta(days=90)),
            )
        )

    # ---- Contacts (every company gets at least one) ---------------------- #
    src_keys = list(sources)
    src_shares = [sources[k]["share"] for k in src_keys]
    used_emails: set[str] = set()
    company_by_id = {c.external_id: c for c in ds.companies}
    for i in range(1, vol["contacts"] + 1):
        company = ds.companies[i - 1] if i <= len(ds.companies) else rng.choice(ds.companies)
        first, last = rng.choice(catalog.FIRST_NAMES), rng.choice(catalog.LAST_NAMES)
        local = f"{_slug(first)}.{_slug(last)}"
        email, n = f"{local}@{company.domain}", 2
        while email in used_emails:
            email, n = f"{local}{n}@{company.domain}", n + 1
        used_emails.add(email)
        ds.contacts.append(
            Contact(
                external_id=f"CON-{i:05d}",
                company_id=company.external_id,
                first_name=first,
                last_name=last,
                email=email,
                lead_source=rng.choices(src_keys, src_shares)[0],
                created_at=_random_date(rng, max(start, company.created_at), as_of - timedelta(days=60)),
            )
        )

    # ---- Deals ------------------------------------------------------------ #
    cweights_deal = [sources[c.lead_source]["deal_weight"] for c in ds.contacts]
    lo, hi = dcfg["sales_cycle_days"]
    for i in range(1, vol["deals"] + 1):
        contact = rng.choices(ds.contacts, cweights_deal)[0]
        created = min(contact.created_at + timedelta(days=rng.randint(0, 75)), as_of - timedelta(days=1))
        close = created + timedelta(days=rng.randint(lo, hi))
        # Deals closing within the invoice lag window stay open, so every won deal has
        # had time to be invoiced and a missing invoice is always a real anomaly.
        if close > as_of - timedelta(days=dcfg["invoice_lag_days"][1]):
            # still open: stage depends on how far along the cycle it is
            progress = (as_of - created).days / max((close - created).days, 1)
            stage = OPEN_STAGES[min(int(progress * len(OPEN_STAGES)), len(OPEN_STAGES) - 1)]
            close_date = None
        else:
            stage = WON if rng.random() < sources[contact.lead_source]["win_rate"] else LOST
            close_date = close
        ds.deals.append(
            Deal(
                external_id=f"DEAL-{i:05d}",
                company_id=contact.company_id,
                contact_id=contact.external_id,
                owner=rng.choice(config["owners"]),
                product=rng.choice(catalog.PRODUCTS),
                amount=_amount(rng, dcfg),
                created_at=created,
                close_date=close_date,
                stage=stage,
            )
        )

    contact_by_id = {c.external_id: c for c in ds.contacts}

    # ---- Billing plan for every won deal ---------------------------------- #
    won = [d for d in ds.deals if d.stage == WON]
    plan: dict[str, dict] = {}
    for d in won:
        inv_date = d.close_date + timedelta(days=rng.randint(*dcfg["invoice_lag_days"]))
        due = inv_date + timedelta(days=dcfg["payment_terms_days"])
        paid = due + timedelta(days=rng.randint(*dcfg["payment_delay_days"]))
        if paid > as_of and due <= as_of:
            paid = _random_date(rng, max(inv_date, due - timedelta(days=10)), as_of)
        plan[d.external_id] = {
            "invoice": True, "invoice_date": inv_date, "due": due,
            "paid_at": paid if paid <= as_of else None,
            "pay_ratio": 1.0, "discount": 0.0, "refund": False,
        }

    # ---- Deal-level anomalies (disjoint sets) ----------------------------- #
    n_won, used = len(won), set()

    def pick(name: str, eligible, weighted: bool = False) -> list[Deal]:
        pool = [d for d in eligible if d.external_id not in used]
        k = round(acfg[name] * n_won)
        if weighted:
            w = [sources[contact_by_id[d.contact_id].lead_source]["bad_payer"] for d in pool]
            chosen = weighted_sample(rng, pool, w, k)
        else:
            chosen = rng.sample(pool, min(k, len(pool)))
        used.update(d.external_id for d in chosen)
        return chosen

    overdue = [d for d in won if plan[d.external_id]["due"] <= as_of]
    for d in pick("missing_invoice", won):
        plan[d.external_id]["invoice"] = False
        ds.anomalies.append(Anomaly("missing_invoice", "deal", d.external_id, d.external_id,
                                    f"Won deal of {d.amount:.2f} with no invoice"))
    for d in pick("unpaid_invoice", overdue, weighted=True):
        plan[d.external_id]["paid_at"] = None
        ds.anomalies.append(Anomaly("unpaid_invoice", "deal", d.external_id, d.external_id,
                                    "Invoice past due with no payment"))
    for d in pick("partial_payment", overdue, weighted=True):
        ratio = round(rng.uniform(0.3, 0.8), 2)
        plan[d.external_id]["pay_ratio"] = ratio
        ds.anomalies.append(Anomaly("partial_payment", "deal", d.external_id, d.external_id,
                                    f"Only {ratio:.0%} collected"))
    for d in pick("amount_mismatch", won):
        disc = round(rng.uniform(0.05, 0.20), 2)
        plan[d.external_id]["discount"] = disc
        ds.anomalies.append(Anomaly("amount_mismatch", "deal", d.external_id, d.external_id,
                                    f"Invoice {disc:.0%} lower than the CRM amount"))
    late_ok = [d for d in overdue if plan[d.external_id]["paid_at"]
               and plan[d.external_id]["paid_at"] <= as_of - timedelta(days=6)]
    for d in pick("late_stage_update", late_ok):
        paid = plan[d.external_id]["paid_at"]
        d.close_date = min(paid + timedelta(days=rng.randint(5, 30)), as_of)
        ds.anomalies.append(Anomaly("late_stage_update", "deal", d.external_id, d.external_id,
                                    f"CRM close date {d.close_date} after payment {paid}"))
    for d in pick("refund", [d for d in overdue if plan[d.external_id]["paid_at"]]):
        plan[d.external_id]["refund"] = True
        ds.anomalies.append(Anomaly("refund", "deal", d.external_id, d.external_id,
                                    "Paid and then fully refunded"))

    # Duplicates: a second rep logs the same sale. They get no invoice of their own.
    next_id = len(ds.deals) + 1
    for d in rng.sample(won, round(acfg["duplicate_deal"] * n_won)):
        dup = Deal(
            external_id=f"DEAL-{next_id:05d}",
            company_id=d.company_id,
            contact_id=d.contact_id,
            owner=rng.choice([o for o in config["owners"] if o != d.owner]),
            product=d.product,
            amount=d.amount,
            created_at=d.created_at + timedelta(days=rng.randint(0, 3)),
            close_date=min(d.close_date + timedelta(days=rng.randint(-3, 3)), as_of),
            stage=WON,
            duplicate_of=d.external_id,
        )
        next_id += 1
        ds.deals.append(dup)
        ds.anomalies.append(Anomaly("duplicate_deal", "deal", dup.external_id, d.external_id,
                                    f"Duplicate of {d.external_id} logged by {dup.owner}"))

    # ---- Customers (only companies that get billed) ----------------------- #
    billed = sorted({d.company_id for d in won if plan[d.external_id]["invoice"]})
    missing_ids = set(rng.sample(billed, round(acfg["missing_external_id"] * len(billed))))
    variants = set(rng.sample(billed, round(acfg["name_variant"] * len(billed))))
    for cid in billed:
        comp = company_by_id[cid]
        name = name_variant(comp.name, rng) if cid in variants else comp.name
        ds.customers.append(Customer(
            crm_company_id=cid,
            external_id=None if cid in missing_ids else cid,
            name=name,
            email=f"billing@{comp.domain}",
        ))
        if cid in variants:
            ds.anomalies.append(Anomaly("name_variant", "customer", cid, None,
                                        f"'{comp.name}' billed as '{name}'"))
        if cid in missing_ids:
            ds.anomalies.append(Anomaly("missing_external_id", "customer", cid, None,
                                        "Billing customer without CRM id; invoices lack deal ref"))

    # ---- Invoices and payments ------------------------------------------- #
    inv_n = pay_n = 1
    for d in sorted(won, key=lambda x: plan[x.external_id]["invoice_date"]):
        p = plan[d.external_id]
        if not p["invoice"]:
            continue
        amount = round(d.amount * (1 - p["discount"]), 2)
        inv = Invoice(
            external_id=f"INV-{inv_n:05d}",
            crm_company_id=d.company_id,
            deal_ref=None if d.company_id in missing_ids else d.external_id,
            product=d.product,
            amount=amount,
            invoice_date=p["invoice_date"],
            due_date=p["due"],
            true_deal_id=d.external_id,
        )
        inv_n += 1
        ds.invoices.append(inv)
        if p["paid_at"]:
            pay = Payment(
                external_id=f"PAY-{pay_n:05d}",
                invoice_id=inv.external_id,
                amount=round(amount * p["pay_ratio"], 2),
                paid_at=p["paid_at"],
                kind="full" if p["pay_ratio"] == 1.0 else "partial",
            )
            if p["refund"]:
                pay.refunded_at = min(pay.paid_at + timedelta(days=rng.randint(3, 20)), as_of)
            pay_n += 1
            ds.payments.append(pay)

    return ds
