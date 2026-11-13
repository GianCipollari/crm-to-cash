"""Incremental extraction from Stripe.

Stripe list endpoints can filter by creation time but objects have no
"last modified" field. So:
- New objects: list everything created at or after the last cursor.
- Changes: invoices are the objects that change after creation (open ->
  paid / void). Every run re-reads, one by one, the invoices that raw
  still has as open.
- Version: each record's `updated_at` is the latest timestamp it carries
  (created, and for invoices its status transitions). A newer version
  means the record changed; the same version means nothing to write.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from extractor.storage import RawStore
from generator.http import RateLimitedClient
from generator.stripe_loader import STRIPE_API_VERSION

log = logging.getLogger(__name__)

PAGE_SIZE = 100
STREAMS = ["customers", "invoices", "payment_intents", "refunds"]
STILL_CHANGING = {"draft", "open"}  # invoice statuses that can still move


def epoch_to_iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def iso_to_epoch(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def version_of(obj: dict) -> str:
    stamps = [obj.get("created")]
    stamps += list((obj.get("status_transitions") or {}).values())
    stamps.append(obj.get("canceled_at"))
    return epoch_to_iso(max(s for s in stamps if isinstance(s, int)))


class StripeExtractor:
    def __init__(self, client: RateLimitedClient, store: RawStore):
        self.client = client
        self.store = store

    @classmethod
    def from_key(cls, api_key: str, store: RawStore) -> "StripeExtractor":
        client = RateLimitedClient(
            "https://api.stripe.com",
            {"Authorization": f"Bearer {api_key}", "Stripe-Version": STRIPE_API_VERSION},
            min_interval=0.08,
        )
        return cls(client, store)

    def _list(self, resource: str, created_gte: int | None) -> list[dict]:
        out, after = [], None
        while True:
            params = {"limit": PAGE_SIZE}
            if created_gte is not None:
                params["created[gte]"] = created_gte
            if after:
                params["starting_after"] = after
            resp = self.client.request("GET", f"/v1/{resource}", params=params)
            out.extend(resp.get("data", []))
            if not resp.get("has_more"):
                return out
            after = resp["data"][-1]["id"]

    def extract(self, resource: str, full: bool = False) -> dict[str, int]:
        stream, table = f"stripe.{resource}", f"raw_stripe_{resource}"
        cursor = None if full else self.store.get_cursor(stream)
        objects = self._list(resource, iso_to_epoch(cursor) if cursor else None)

        rechecked = 0
        if resource == "invoices" and not full:
            seen = {o["id"] for o in objects}
            for rid, payload in self.store.payloads(table).items():
                if payload.get("status") in STILL_CHANGING and rid not in seen:
                    objects.append(self.client.request("GET", f"/v1/invoices/{rid}"))
                    rechecked += 1

        rows = [{"id": o["id"], "updated_at": version_of(o), "payload": o} for o in objects]
        counts = self.store.upsert(table, rows)
        if objects:
            newest_created = max(o["created"] for o in objects)
            if not cursor or newest_created > iso_to_epoch(cursor):
                self.store.set_cursor(stream, epoch_to_iso(newest_created))
        counts["fetched"] = len(objects) - rechecked
        counts["rechecked"] = rechecked
        counts["total_in_raw"] = self.store.count(table)
        log.info("%s: %s", stream, counts)
        return counts

    def extract_all(self, full: bool = False) -> dict[str, dict[str, int]]:
        return {r: self.extract(r, full) for r in STREAMS}
