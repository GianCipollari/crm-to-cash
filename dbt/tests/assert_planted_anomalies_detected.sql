-- Ground-truth test: every anomaly the generator planted must be detected.
-- Returns the planted anomalies that mart_data_quality_issues missed.

select
    m.anomaly_type,
    m.object_type,
    m.external_id,
    m.detail
from {{ ref('anomalies_manifest') }} as m
left join {{ ref('mart_data_quality_issues') }} as q
    on q.issue_type = m.anomaly_type
    and q.external_id = m.external_id
where q.issue_id is null
