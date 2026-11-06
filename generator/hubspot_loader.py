"""Loads the synthetic CRM data into a HubSpot developer test account.

Order: custom properties -> companies -> contacts (+ company association)
-> deals (+ company and contact associations). Uses the batch endpoints
(100 records per call), so the full seed is about 25 API calls.

Notes on HubSpot behaviour (see docs/decisions/0001-synthetic-data.md):
- HubSpot sets `createdate` to the load time, so the original dates live
  in custom date properties (source_created_date, deal_created_date).
- Owners must be real users of the portal, so the sales rep is stored as a
  custom enumeration property (`sales_rep`).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from generator.http import ApiError, RateLimitedClient
from generator.model import Dataset
from generator.state import LoadState

log = logging.getLogger(__name__)

BATCH_SIZE = 100

# HubSpot-defined association type ids (CRM v4 associations).
# Verify against https://developers.hubspot.com/docs/api/crm/associations if a call fails.
ASSOC_CONTACT_TO_COMPANY = 279
ASSOC_DEAL_TO_COMPANY = 341
ASSOC_DEAL_TO_CONTACT = 3


def _ms(d: date) -> int:
    """HubSpot date properties expect midnight UTC as epoch milliseconds."""
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def _assoc(to_id: str, type_id: int) -> dict:
    return {"to": {"id": to_id},
            "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": type_id}]}


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


class HubSpotLoader:
    def __init__(self, token: str, state: LoadState, config: dict, client: RateLimitedClient | None = None):
        self.state = state
        self.config = config
        # Private apps allow more, but 0.15s spacing keeps us well under any tier's limit.
        self.client = client or RateLimitedClient(
            "https://api.hubapi.com",
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            min_interval=0.15,
        )

    # ------------------------------------------------------------------ #
    def property_definitions(self) -> list[tuple[str, dict]]:
        text = {"type": "string", "fieldType": "text"}
        dt = {"type": "date", "fieldType": "date"}

        def enum(values: list[tuple[str, str]]) -> dict:
            return {"type": "enumeration", "fieldType": "select",
                    "options": [{"label": lbl, "value": val, "displayOrder": i}
                                for i, (val, lbl) in enumerate(values)]}

        sources = [(k, v["label"]) for k, v in self.config["lead_sources"].items()]
        reps = [(o.lower().replace(" ", "_"), o) for o in self.config["owners"]]
        defs = [
            ("companies", {"name": "external_id", "label": "External ID", "hasUniqueValue": True, **text}),
            ("companies", {"name": "tax_id", "label": "Tax ID", **text}),
            ("contacts", {"name": "external_id", "label": "External ID", "hasUniqueValue": True, **text}),
            ("contacts", {"name": "lead_source", "label": "Lead source", **enum(sources)}),
            ("contacts", {"name": "source_created_date", "label": "Source created date", **dt}),
            ("deals", {"name": "external_id", "label": "External ID", "hasUniqueValue": True, **text}),
            ("deals", {"name": "sales_rep", "label": "Sales rep", **enum(reps)}),
            ("deals", {"name": "deal_created_date", "label": "Deal created date", **dt}),
        ]
        groups = {"companies": "companyinformation", "contacts": "contactinformation", "deals": "dealinformation"}
        return [(obj, {**body, "groupName": groups[obj]}) for obj, body in defs]

    def ensure_properties(self) -> None:
        for obj, body in self.property_definitions():
            try:
                self.client.request("POST", f"/crm/v3/properties/{obj}", json=body)
                log.info("Created property %s.%s", obj, body["name"])
            except ApiError as err:
                if err.status == 409:  # already exists: fine, the call is idempotent for us
                    log.info("Property %s.%s already exists", obj, body["name"])
                else:
                    raise

    # ------------------------------------------------------------------ #
    def _batch_create(self, obj: str, kind: str, inputs: list[tuple[str, dict]]) -> None:
        """inputs = [(external_id, hubspot_input)], skipping ids already loaded."""
        pending = [(eid, body) for eid, body in inputs if not self.state.has(kind, eid)]
        log.info("%s: %d to create, %d already loaded", obj, len(pending), len(inputs) - len(pending))
        for chunk in _chunks(pending, BATCH_SIZE):
            resp = self.client.request(
                "POST", f"/crm/v3/objects/{obj}/batch/create",
                json={"inputs": [body for _, body in chunk]},
            )
            # Results are not guaranteed to come back in input order: map by external_id.
            for result in resp.get("results", []):
                self.state.set(kind, result["properties"]["external_id"], result["id"])
            for error in resp.get("errors", []):
                log.error("%s batch error: %s", obj, error.get("message"))
            self.state.save()

    def load(self, ds: Dataset) -> None:
        self.ensure_properties()

        self._batch_create("companies", "company", [
            (c.external_id, {"properties": {
                "external_id": c.external_id, "name": c.name, "domain": c.domain,
                "country": c.country, "tax_id": c.tax_id,
            }})
            for c in ds.companies
        ])

        self._batch_create("contacts", "contact", [
            (c.external_id, {
                "properties": {
                    "external_id": c.external_id, "firstname": c.first_name, "lastname": c.last_name,
                    "email": c.email, "lead_source": c.lead_source,
                    "source_created_date": _ms(c.created_at),
                },
                "associations": [_assoc(self.state.get("company", c.company_id), ASSOC_CONTACT_TO_COMPANY)],
            })
            for c in ds.contacts if self.state.has("company", c.company_id)
        ])

        deal_inputs = []
        for d in ds.deals:
            props = {
                "external_id": d.external_id, "dealname": f"{d.product} - {d.company_id}",
                "amount": f"{d.amount:.2f}", "pipeline": "default", "dealstage": d.stage,
                "sales_rep": d.owner.lower().replace(" ", "_"),
                "deal_created_date": _ms(d.created_at),
            }
            if d.close_date:
                props["closedate"] = _ms(d.close_date)
            assocs = []
            if self.state.has("company", d.company_id):
                assocs.append(_assoc(self.state.get("company", d.company_id), ASSOC_DEAL_TO_COMPANY))
            if self.state.has("contact", d.contact_id):
                assocs.append(_assoc(self.state.get("contact", d.contact_id), ASSOC_DEAL_TO_CONTACT))
            deal_inputs.append((d.external_id, {"properties": props, "associations": assocs}))
        self._batch_create("deals", "deal", deal_inputs)

        log.info("HubSpot load finished with %d API calls", self.client.calls)
