# Account setup (one time, free)

Both accounts are free and contain only synthetic data. Menu names change from time to
time; if a step does not match exactly, search the provider's docs for the same concept.

## 1. HubSpot developer test account

1. Create a free developer account at <https://developers.hubspot.com/>.
2. Inside it, open **Test accounts** and click **Create developer test account**.
   Test accounts include a 90-day trial of enterprise features and can be renewed.
3. Enter the test account and create a **private app**
   (Settings > Integrations > Private Apps; it may appear as *Legacy apps*).
4. Give it these scopes:
   - `crm.objects.companies.read`, `crm.objects.companies.write`
   - `crm.objects.contacts.read`, `crm.objects.contacts.write`
   - `crm.objects.deals.read`, `crm.objects.deals.write`
   - `crm.schemas.companies.read`, `crm.schemas.companies.write`
   - `crm.schemas.contacts.read`, `crm.schemas.contacts.write`
   - `crm.schemas.deals.read`, `crm.schemas.deals.write`
5. Copy the access token (`pat-...`) into `.env` as `HUBSPOT_TOKEN`.

## 2. Stripe test mode

1. Create a free account at <https://dashboard.stripe.com/register>. No business
   activation is needed for test mode.
2. Switch to **test mode** (or a sandbox).
3. Developers > API keys: copy the **secret key** (`sk_test_...`) into `.env` as
   `STRIPE_TEST_KEY`. The loader refuses to run with a live key.

## 3. Run

```bash
cp .env.example .env      # then paste both keys
make install
make test                 # offline checks
make preview              # build the company locally and inspect out/dataset/*.csv
make seed-hubspot         # ~25 API calls
make seed-stripe          # a few hundred API calls, about a minute
```

If a load is interrupted, run the same command again: it resumes from `out/state/`.
To start over in a clean account, delete `out/state/` **and** create a new test account,
otherwise the remote records from the first run remain.
