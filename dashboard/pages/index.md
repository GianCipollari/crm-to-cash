---
title: CRM-to-Cash
---

Sales says a deal is closed-won; finance says the money never arrived. This dashboard
reconciles HubSpot (CRM) with Stripe (billing) for a fictional B2B SaaS company and
shows where the gap comes from. Data is synthetic and refreshed every day by the
[pipeline](https://github.com/GianCipollari/crm-to-cash).

```sql kpis
select
    count(*) filter (where not is_duplicate)                              as won_deals,
    sum(case when not is_duplicate then deal_amount else 0 end)           as won_amount,
    sum(net_collected)                                                    as collected,
    sum(net_collected)
        / nullif(sum(case when not is_duplicate then deal_amount else 0 end), 0) as collection_rate,
    sum(case when reconciliation_status in ('missing_invoice', 'unpaid_overdue', 'partial_payment',
                                            'amount_mismatch', 'refunded')
             then gap_amount else 0 end)                                  as problem_gap
from warehouse.reconciliation
```

<BigValue data={kpis} value=won_deals title="Won deals" />
<BigValue data={kpis} value=won_amount title="Won in the CRM" fmt=usd0 />
<BigValue data={kpis} value=collected title="Collected (net)" fmt=usd0 />
<BigValue data={kpis} value=collection_rate title="Collection rate" fmt=pct1 />
<BigValue data={kpis} value=problem_gap title="Gap from data problems" fmt=usd0 />

## Where to look

- [Reconciliation](/reconciliation): what was won, billed and collected, and why they differ
- [Lead funnel](/funnel): which lead sources bring customers who actually pay
- [Data quality](/data-quality): every problem detected in the CRM and billing data

Open invoices that are not yet due are normal receivables and are not counted as a problem.
