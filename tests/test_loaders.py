"""Loader tests with fake HTTP: no network, no accounts needed."""

from pathlib import Path

import pytest

from generator.http import ApiError, RateLimitedClient
from generator.hubspot_loader import HubSpotLoader
from generator.model import build_dataset, load_config
from generator.state import LoadState
from generator.stripe_loader import StripeLoader, _form

CONFIG = load_config(Path(__file__).resolve().parent.parent / "generator" / "config.yaml")


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.content = b"x"
        self.text = str(payload)

    def json(self):
        return self._payload


class ScriptedSession:
    """Returns pre-scripted responses in order and records every request."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)


def make_client(session, **kw):
    return RateLimitedClient("https://api.example.com", {}, session=session,
                             sleep=kw.pop("sleep", lambda s: None), **kw)


# --------------------------------------------------------------------------- #
# HTTP client
# --------------------------------------------------------------------------- #
def test_retries_on_429_using_retry_after():
    slept = []
    session = ScriptedSession([FakeResponse(429, headers={"Retry-After": "2"}), FakeResponse(200, {"ok": 1})])
    client = make_client(session, sleep=slept.append, min_interval=0)
    assert client.request("GET", "/x") == {"ok": 1}
    assert 2.0 in slept and len(session.requests) == 2


def test_retries_on_5xx_with_backoff_then_gives_up():
    session = ScriptedSession([FakeResponse(503)] * 3)
    client = make_client(session, max_retries=2, min_interval=0)
    with pytest.raises(ApiError) as err:
        client.request("GET", "/x")
    assert err.value.status == 503 and len(session.requests) == 3


def test_client_errors_are_not_retried():
    session = ScriptedSession([FakeResponse(400, {"message": "bad"})])
    with pytest.raises(ApiError):
        make_client(session, min_interval=0).request("POST", "/x")
    assert len(session.requests) == 1


# --------------------------------------------------------------------------- #
# HubSpot
# --------------------------------------------------------------------------- #
class FakeHubSpot:
    """Echoes batch creates back with fake ids, like the real API does."""
    def __init__(self):
        self.calls = []
        self.next_id = 1

    def request(self, method, path, json=None, **kw):
        self.calls.append(path)
        if path.endswith("/batch/create"):
            results = []
            for body in json["inputs"]:
                results.append({"id": str(self.next_id), "properties": body["properties"]})
                self.next_id += 1
            return {"results": results[::-1]}  # reversed on purpose: order is not guaranteed
        return {}


def test_hubspot_batches_and_resumes(tmp_path):
    ds = build_dataset(CONFIG)
    fake = FakeHubSpot()
    state = LoadState(tmp_path / "hubspot.json")
    HubSpotLoader("token", state, CONFIG, client=fake).load(ds)

    batch_calls = [c for c in fake.calls if c.endswith("/batch/create")]
    expected = sum(-(-n // 100) for n in (len(ds.companies), len(ds.contacts), len(ds.deals)))
    assert len(batch_calls) == expected  # ~ 2 + 10 + 6 calls, far below any rate limit
    assert len(state.data["deal"]) == len(ds.deals)

    # Second run with the saved state creates nothing new.
    fake2 = FakeHubSpot()
    HubSpotLoader("token", LoadState(tmp_path / "hubspot.json"), CONFIG, client=fake2).load(ds)
    assert not [c for c in fake2.calls if c.endswith("/batch/create")]


# --------------------------------------------------------------------------- #
# Stripe
# --------------------------------------------------------------------------- #
def test_stripe_form_encoding():
    assert _form({"name": "A", "metadata": {"k": "v"}, "types": ["card"], "confirm": True}) == {
        "name": "A", "metadata[k]": "v", "types[0]": "card", "confirm": "true",
    }


def test_stripe_refuses_live_keys(tmp_path):
    with pytest.raises(ValueError):
        StripeLoader("sk_live_123", LoadState(tmp_path / "s.json"), CONFIG)


class FakeStripe:
    def __init__(self):
        self.calls = []
        self.n = 0

    def request(self, method, path, data=None, headers=None, **kw):
        self.calls.append((path, (headers or {}).get("Idempotency-Key")))
        self.n += 1
        resp = {"id": f"obj_{self.n}"}
        if path.endswith("/pay"):
            resp["payment_intent"] = f"pi_{self.n}"
        return resp


def test_stripe_loads_everything_with_idempotency_keys(tmp_path):
    ds = build_dataset(CONFIG)
    fake = FakeStripe()
    state = LoadState(tmp_path / "stripe.json")
    StripeLoader("sk_test_123", state, CONFIG, client=fake).load(ds)

    assert len(state.data["invoice"]) == len(ds.invoices)
    assert len(state.data["payment"]) == len(ds.payments)
    refunds = [c for c in fake.calls if c[0] == "/v1/refunds"]
    assert len(refunds) == sum(1 for p in ds.payments if p.refunded_at)
    creates = [c for c in fake.calls if not c[0].startswith("/v1/payment_intents/pi_")]
    assert all(key for _, key in creates)  # every create is idempotent

    fake2 = FakeStripe()
    StripeLoader("sk_test_123", LoadState(tmp_path / "stripe.json"), CONFIG, client=fake2).load(ds)
    assert fake2.calls == []
