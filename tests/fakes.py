"""In-memory stand-ins for the HubSpot and Stripe endpoints the generator uses.

They implement just enough behaviour (storage, filters, paging, idempotency)
to test the daily runner end to end without network access.
"""

from __future__ import annotations

import re
from itertools import count

from generator.http import ApiError
from generator.hubspot_loader import _ms


class FakeHubSpot:
    def __init__(self):
        self.objects = {"companies": {}, "contacts": {}, "deals": {}}  # hs id -> properties
        self.assoc = {}  # (obj, hs id) -> {"companies": id, "contacts": id}
        self.properties = set()
        self.ids = count(1000)
        self.calls = []

    # helpers for test setup
    def add(self, obj: str, props: dict, company: str | None = None) -> str:
        hid = str(next(self.ids))
        self.objects[obj][hid] = {k: (str(v) if v is not None else None) for k, v in props.items()}
        if company:
            self.assoc[(obj, hid)] = {"companies": company}
        return hid

    def by_external(self, obj: str) -> dict[str, dict]:
        return {p.get("external_id"): {"id": i, **p} for i, p in self.objects[obj].items()}

    def _match(self, props: dict, flt: dict) -> bool:
        value = props.get(flt["propertyName"])
        op = flt["operator"]
        if op == "IN":
            return value in flt["values"]
        if op == "EQ":
            return value == flt["value"]
        if op == "GTE":
            return value is not None and int(value) >= int(flt["value"])
        raise NotImplementedError(op)

    def request(self, method: str, path: str, json=None, **kw):
        self.calls.append((method, path))
        if path.startswith("/crm/v3/properties/"):
            key = (path, json["name"])
            if key in self.properties:
                raise ApiError(409, "exists", path)
            self.properties.add(key)
            return {}

        m = re.match(r"/crm/v3/objects/(\w+)/batch/(read|create|update)$", path)
        if m:
            obj, action = m.groups()
            store = self.objects[obj]
            if action == "read":
                if json.get("idProperty") == "external_id":
                    index = self.by_external(obj)
                    rows = [index[i["id"]] for i in json["inputs"] if i["id"] in index]
                else:
                    rows = [{"id": i["id"], **store[i["id"]]} for i in json["inputs"] if i["id"] in store]
                return {"results": [{"id": r["id"], "properties": {k: v for k, v in r.items() if k != "id"}}
                                    for r in rows]}
            if action == "create":
                out = []
                for item in json["inputs"]:
                    hid = self.add(obj, item["properties"])
                    links = {}
                    for a in item.get("associations", []):
                        target = a["to"]["id"]
                        kind = "companies" if target in self.objects["companies"] else "contacts"
                        links[kind] = target
                    self.assoc[(obj, hid)] = links
                    out.append({"id": hid, "properties": self.objects[obj][hid]})
                return {"results": out}
            for item in json["inputs"]:
                store[item["id"]].update({k: str(v) for k, v in item["properties"].items()})
            return {"results": []}

        if path == "/crm/v3/objects/deals/search":
            rows = [(hid, p) for hid, p in sorted(self.objects["deals"].items(), key=lambda x: int(x[0]))
                    if all(self._match(p, f) for f in json["filterGroups"][0]["filters"])]
            start = int(json.get("after") or 0)
            page = rows[start:start + json["limit"]]
            resp = {"results": [{"id": h, "properties": dict(p)} for h, p in page]}
            if start + json["limit"] < len(rows):
                resp["paging"] = {"next": {"after": str(start + json["limit"])}}
            return resp

        if path == "/crm/v4/associations/deals/companies/batch/read":
            return {"results": [
                {"from": {"id": i["id"]}, "to": [{"toObjectId": int(self.assoc[("deals", i["id"])]["companies"])}]}
                for i in json["inputs"] if self.assoc.get(("deals", i["id"]), {}).get("companies")]}
        raise NotImplementedError(path)


class FakeStripe:
    def __init__(self):
        self.customers, self.invoices, self.items, self.intents = {}, {}, [], {}
        self.pms = {}  # customer -> pm id
        self.idem = {}
        self.n = count(1)
        self.calls = []

    def _meta(self, data: dict) -> dict:
        return {k[9:-1]: v for k, v in data.items() if k.startswith("metadata[")}

    def add_invoice(self, customer: str, meta: dict, status: str = "open", amount: int = 100000) -> str:
        iid = f"in_{next(self.n)}"
        self.invoices[iid] = {"id": iid, "customer": customer, "status": status, "metadata": dict(meta),
                              "amount_due": amount, "payment_intent": None}
        return iid

    def _search(self, store: dict, query: str) -> list:
        m = re.match(r"metadata\['(\w+)'\]:'(.+)'", query)
        if m:
            return [o for o in store.values() if o["metadata"].get(m.group(1)) == m.group(2)]
        m = re.match(r"email:'(.+)'", query)
        return [o for o in store.values() if o.get("email") == m.group(1)]

    def request(self, method: str, path: str, data=None, params=None, headers=None, **kw):
        self.calls.append((method, path))
        key = (headers or {}).get("Idempotency-Key")
        if key and key in self.idem:
            return self.idem[key]
        resp = self._handle(method, path, data or {}, params or {})
        if key:
            self.idem[key] = resp
        return resp

    def _handle(self, method, path, data, params):
        if path == "/v1/customers/search":
            return {"data": self._search(self.customers, params["query"])}
        if path == "/v1/invoices/search":
            return {"data": self._search(self.invoices, params["query"])}
        if path == "/v1/customers" and method == "POST":
            cid = f"cus_{next(self.n)}"
            self.customers[cid] = {"id": cid, "email": data.get("email"), "metadata": self._meta(data)}
            return self.customers[cid]
        if path == "/v1/invoices" and method == "POST":
            return self.invoices[self.add_invoice(data["customer"], self._meta(data), status="draft", amount=0)]
        if path == "/v1/invoices" and method == "GET":
            rows = sorted((i for i in self.invoices.values() if i["status"] == params["status"]),
                          key=lambda i: int(i["id"][3:]))
            if "starting_after" in params:
                rows = rows[[r["id"] for r in rows].index(params["starting_after"]) + 1:]
            page = rows[: params["limit"]]
            return {"data": page, "has_more": len(rows) > len(page)}
        if path == "/v1/invoiceitems":
            self.items.append(data)
            self.invoices[data["invoice"]]["amount_due"] += int(data["amount"])
            return {"id": f"ii_{next(self.n)}"}
        m = re.match(r"/v1/invoices/(in_\d+)/(finalize|pay)$", path)
        if m:
            inv = self.invoices[m.group(1)]
            if m.group(2) == "finalize":
                inv["status"] = "open"
            else:
                assert inv["status"] == "open", "paying an invoice that is not open"
                inv["status"] = "paid"
                pi = f"pi_{next(self.n)}"
                self.intents[pi] = {"metadata": {}}
                inv["payment_intent"] = pi
            return inv
        m = re.match(r"/v1/payment_intents/(pi_\d+)$", path)
        if m:
            self.intents[m.group(1)]["metadata"].update(self._meta(data))
            return {"id": m.group(1)}
        m = re.match(r"/v1/customers/(cus_\d+)/payment_methods$", path)
        if m:
            pm = self.pms.get(m.group(1))
            return {"data": [{"id": pm}] if pm else []}
        if path == "/v1/payment_methods/pm_card_visa/attach":
            pm = f"pm_{next(self.n)}"
            self.pms[data["customer"]] = pm
            return {"id": pm}
        raise NotImplementedError(f"{method} {path}")


def ms(d) -> str:
    return str(_ms(d))
