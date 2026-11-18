---
title: Reconciliation
---

Every won deal gets one status that explains the difference between what sales
reported and what was collected.

```sql by_status
select
    reconciliation_status,
    count(*)         as deals,
    sum(gap_amount)  as gap_amount
from warehouse.reconciliation
group by 1
order by gap_amount desc
```

<BarChart
    data={by_status}
    x=reconciliation_status
    y=gap_amount
    swapXY=true
    yFmt=usd0
    title="Gap by reconciliation status"
/>

```sql by_month
select
    close_month,
    sum(case when not is_duplicate then deal_amount else 0 end)  as won,
    sum(coalesce(invoice_amount, 0))                             as invoiced,
    sum(net_collected)                                           as collected
from warehouse.reconciliation
group by 1
order by 1
```

<BarChart
    data={by_month}
    x=close_month
    y={['won', 'invoiced', 'collected']}
    type=grouped
    yFmt=usd0
    title="Won vs invoiced vs collected, by close month"
/>

```sql by_rep
select
    sales_rep,
    count(*) filter (where not is_duplicate)                       as won_deals,
    sum(case when not is_duplicate then deal_amount else 0 end)    as won,
    sum(net_collected)                                             as collected,
    sum(net_collected)
        / nullif(sum(case when not is_duplicate then deal_amount else 0 end), 0) as collection_rate,
    count(*) filter (where reconciliation_status <> 'reconciled'
                     and reconciliation_status <> 'not_yet_due')   as deals_with_issues
from warehouse.reconciliation
group by 1
order by won desc
```

## By sales rep

<DataTable data={by_rep}>
    <Column id=sales_rep />
    <Column id=won_deals />
    <Column id=won fmt=usd0 />
    <Column id=collected fmt=usd0 />
    <Column id=collection_rate fmt=pct1 />
    <Column id=deals_with_issues />
</DataTable>

```sql problem_deals
select
    external_id,
    sales_rep,
    close_date,
    deal_amount,
    invoice_amount,
    net_collected,
    gap_amount,
    reconciliation_status
from warehouse.reconciliation
where reconciliation_status not in ('reconciled', 'not_yet_due', 'pending_invoice')
order by gap_amount desc
```

## Deals that need attention

<DataTable data={problem_deals} rows=15 search=true>
    <Column id=external_id title="Deal" />
    <Column id=sales_rep />
    <Column id=close_date />
    <Column id=deal_amount fmt=usd0 />
    <Column id=invoice_amount fmt=usd0 />
    <Column id=net_collected fmt=usd0 />
    <Column id=gap_amount fmt=usd0 />
    <Column id=reconciliation_status title="Status" />
</DataTable>
