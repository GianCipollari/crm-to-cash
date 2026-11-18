{{ config(severity='warn') }}

-- The other direction: problems detected that were not planted. Some are expected and
-- excluded here (late payers from the daily job, HubSpot's sample contacts). Anything
-- else shows up as a warning to investigate: a real data problem or a false positive.

select
    q.issue_type,
    q.external_id,
    q.related_deal_id,
    q.detail
from {{ ref('mart_data_quality_issues') }} as q
left join {{ ref('anomalies_manifest') }} as m
    on q.issue_type = m.anomaly_type
    and q.external_id = m.external_id
where m.external_id is null
  and q.issue_type not in ('unpaid_invoice', 'contact_without_external_id')
