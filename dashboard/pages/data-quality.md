---
title: Data quality
---

Every problem the pipeline detects in the CRM and billing data. Each rule is tested
against a list of problems planted on purpose in the synthetic data, so detection is
verified on every run.

```sql by_type
select
    issue_label                       as issue_type,
    count(*)                          as issues,
    sum(coalesce(amount_at_risk, 0))  as amount_at_risk
from marts.issues
group by 1
order by issues desc
```

<BarChart
    data={by_type}
    x=issue_type
    y=issues
    swapXY=true
    title="Issues by type"
    xAxisTitle=false
/>

**How to read:** how many records have each problem. Amount at risk, in the table, is the
money involved; some problems (name differences, missing ids) have none but break matching.

<DataTable data={by_type}>
    <Column id=issue_type title="Issue" />
    <Column id=issues />
    <Column id=amount_at_risk fmt=usd0 />
</DataTable>

```sql all_issues
select issue_label as issue_type, object_type, external_id, related_deal_id, amount_at_risk, detail
from marts.issues
order by amount_at_risk desc nulls last
```

## All detected issues

<DataTable data={all_issues} rows=20 search=true>
    <Column id=issue_type title="Issue" />
    <Column id=object_type title="Object" />
    <Column id=external_id title="Record" />
    <Column id=related_deal_id title="Related deal" />
    <Column id=amount_at_risk fmt=usd0 />
    <Column id=detail />
</DataTable>
