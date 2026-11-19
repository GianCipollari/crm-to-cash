---
title: Reconciliation
---

Every won deal gets one status that explains the difference between what sales
reported and what was collected.

```sql by_status
select
    status_label,
    count(*)         as deals,
    sum(gap_amount)  as gap_amount
from marts.reconciliation
group by 1
having sum(gap_amount) > 0
order by gap_amount desc
```

<BarChart
    data={by_status}
    x=status_label
    y=gap_amount
    swapXY=true
    yFmt=usd0
    title="Where the gap comes from"
    xAxisTitle=false
/>

**How to read:** each bar is money won in the CRM but not in the bank, grouped by cause.
"Unpaid, not yet due" and "Invoice pending" are normal timing; the other bars are problems
to fix. Statuses with no gap (reconciled deals, duplicates) are not shown.

```sql by_month
select
    close_month,
    sum(case when not is_duplicate then deal_amount else 0 end)  as won,
    sum(coalesce(invoice_amount, 0))                             as invoiced,
    sum(net_collected)                                           as collected
from marts.reconciliation
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

**How to read:** in a healthy month the three bars are the same height. Recent months are
lower on the right because invoices are not due yet.

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
from marts.reconciliation
group by 1
order by won desc
```

## By sales rep

Deals with issues excludes reconciled and not-yet-due deals.

<DataTable data={by_rep}>
    <Column id=sales_rep title="Sales rep" />
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
    status_label
from marts.reconciliation
where reconciliation_status not in ('reconciled', 'not_yet_due', 'pending_invoice')
order by gap_amount desc
```

## Deals that need attention

Every won deal with a problem, largest gap first. Search by deal, rep or status.

<DataTable data={problem_deals} rows=15 search=true>
    <Column id=external_id title="Deal" />
    <Column id=sales_rep title="Sales rep" />
    <Column id=close_date />
    <Column id=deal_amount fmt=usd0 />
    <Column id=invoice_amount fmt=usd0 />
    <Column id=net_collected fmt=usd0 />
    <Column id=gap_amount fmt=usd0 />
    <Column id=status_label title="Status" />
</DataTable>
