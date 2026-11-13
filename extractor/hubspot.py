"""Incremental extraction from HubSpot.

For each object (companies, contacts, deals) it asks the Search API for the
records modified since the last cursor, page by page, attaches their
associations and writes them to raw tables. The cursor only moves forward
after the records are stored, so a failed run is simply repeated.
"""

from __future__ import annotations

import logging
from datetime import datetime

from extractor.storage import RawStore
from generator.http import RateLimitedClient

log = logging.getLogger(__name__)

PAGE_SIZE = 100

# object -> (property used as modification time, properties to extract, associations to fetch)
STREAMS = {
    "companies": ("hs_lastmodifieddate",
                  ["external_id", "name", "domain", "country", "tax_id", "createdate"],
                  []),
    "contacts": ("lastmodifieddate",  # contacts use a different property name
                 ["external_id", "firstname", "lastname", "email", "lead_source",
                  "source_created_date", "lifecyclestage", "createdate"],
                 ["companies"]),
    "deals": ("hs_lastmodifieddate",
              ["external_id", "dealname", "amount", "pipeline", "dealstage", "closedate",
               "sales_rep", "deal_created_date", "sim_last_moved", "createdate"],
              ["companies", "contacts"]),
}


def iso_to_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


class HubSpotExtractor:
    def __init__(self, client: RateLimitedClient, store: RawStore):
        self.client = client
        self.store = store

    @classmethod
    def from_token(cls, token: str, store: RawStore) -> "HubSpotExtractor":
        client = RateLimitedClient(
            "https://api.hubapi.com",
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            min_interval=0.25,  # the Search API allows fewer requests per second
        )
        return cls(client, store)

    def _search(self, obj: str, modified_prop: str, props: list[str], since: str | None) -> list[dict]:
        """All records modified at or after `since` (everything when since is None)."""
        results, after = [], None
        while True:
            body = {
                "properties": props + [modified_prop],
                "sorts": [{"propertyName": modified_prop, "direction": "ASCENDING"}],
                "limit": PAGE_SIZE,
            }
            if since:
                body["filterGroups"] = [{"filters": [
                    {"propertyName": modified_prop, "operator": "GTE", "value": str(iso_to_ms(since))}]}]
            if after:
                body["after"] = after
            resp = self.client.request("POST", f"/crm/v3/objects/{obj}/search", json=body)
            results.extend(resp.get("results", []))
            after = resp.get("paging", {}).get("next", {}).get("after")
            if not after:
                return results

    def _associations(self, obj: str, to_obj: str, ids: list[str]) -> dict[str, list[str]]:
        links: dict[str, list[str]] = {}
        for i in range(0, len(ids), PAGE_SIZE):
            resp = self.client.request(
                "POST", f"/crm/v4/associations/{obj}/{to_obj}/batch/read",
                json={"inputs": [{"id": x} for x in ids[i:i + PAGE_SIZE]]})
            for r in resp.get("results", []):
                links[str(r["from"]["id"])] = [str(t["toObjectId"]) for t in r.get("to", [])]
        return links

    def extract(self, obj: str, full: bool = False) -> dict[str, int]:
        modified_prop, props, assoc_targets = STREAMS[obj]
        stream = f"hubspot.{obj}"
        since = None if full else self.store.get_cursor(stream)
        records = self._search(obj, modified_prop, props, since)

        ids = [r["id"] for r in records]
        assoc = {t: self._associations(obj, t, ids) for t in assoc_targets} if ids else {}
        rows = []
        for r in records:
            payload = {**r, "associations": {t: assoc[t].get(r["id"], []) for t in assoc_targets}}
            rows.append({"id": r["id"], "updated_at": r["updatedAt"], "payload": payload})

        counts = self.store.upsert(f"raw_hubspot_{obj}", rows)
        if rows:  # GTE on the next run re-reads the boundary records; they come back as unchanged
            self.store.set_cursor(stream, max(r["updated_at"] for r in rows))
        counts["fetched"] = len(rows)
        counts["total_in_raw"] = self.store.count(f"raw_hubspot_{obj}")
        log.info("%s: %s", stream, counts)
        return counts

    def extract_all(self, full: bool = False) -> dict[str, dict[str, int]]:
        return {obj: self.extract(obj, full) for obj in STREAMS}
