---
title: Lead funnel
---

Lead sources compared by what they collect, not only by what they close.
Each contact is followed from lead to deal, won deal and payment.

```sql by_source
select
    lead_source_label                                             as lead_source,
    count(*)                                                      as contacts,
    avg(case when reached_deal then 1.0 else 0 end)               as deal_rate,
    avg(case when reached_won then 1.0 else 0 end)                as won_rate,
    avg(case when reached_paid then 1.0 else 0 end)               as paid_rate,
    sum(won_amount)                                               as won_amount,
    sum(collected_amount)                                         as collected_amount,
    sum(collected_amount) / nullif(sum(won_amount), 0)            as collection_rate,
    sum(collected_amount) / count(*)                              as collected_per_contact,
    median(days_lead_to_cash)                                     as median_days_to_cash
from marts.funnel
group by 1
order by collected_per_contact desc
```

<BarChart
    data={by_source}
    x=lead_source
    y=collected_per_contact
    yFmt=usd0
    title="Cash collected per contact, by lead source"
    xAxisTitle=false
/>

**How to read:** this is the number to compare sources by. A source can win many deals and
still rank low here if its customers pay late or not at all.

<BarChart
    data={by_source}
    x=lead_source
    y={['deal_rate', 'won_rate', 'paid_rate']}
    type=grouped
    yFmt=pct0
    title="Conversion at each stage, by lead source"
    xAxisTitle=false
/>

**How to read:** share of contacts that reached a deal, a won deal and a payment. The gap
between the second and third bar is customers who signed but did not pay.

<DataTable data={by_source}>
    <Column id=lead_source title="Lead source" />
    <Column id=contacts />
    <Column id=deal_rate fmt=pct1 />
    <Column id=won_rate fmt=pct1 />
    <Column id=paid_rate fmt=pct1 />
    <Column id=won_amount fmt=usd0 />
    <Column id=collected_amount fmt=usd0 />
    <Column id=collection_rate fmt=pct1 />
    <Column id=median_days_to_cash title="Median days lead to cash" />
</DataTable>
