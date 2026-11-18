-- One row per real contact (HubSpot's sample contacts excluded), following the lead
-- through the funnel: contact -> deal -> won deal -> money collected.
-- Answers business question 3: which lead sources bring customers who actually pay.

with contacts as (

    select * from {{ ref('stg_hubspot__contacts') }}
    where has_external_id

),

deals as (

    select contact_id, count(*) as deals_count
    from {{ ref('stg_hubspot__deals') }}
    group by 1

),

won as (

    -- duplicates are excluded so a sale logged twice is counted once
    select
        contact_id,
        count(*)                as won_deals_count,
        sum(deal_amount)        as won_amount,
        sum(net_collected)      as collected_amount,
        min(close_date)         as first_won_date,
        min(last_paid_date)     as first_paid_date
    from {{ ref('fct_deal_reconciliation') }}
    where not is_duplicate
    group by 1

)

select
    c.contact_id,
    c.external_id,
    c.company_id,
    c.lead_source,
    c.source_created_date,
    {{ year_month('c.source_created_date') }}        as cohort_month,

    coalesce(d.deals_count, 0)                       as deals_count,
    coalesce(w.won_deals_count, 0)                   as won_deals_count,
    coalesce(w.won_amount, 0)                        as won_amount,
    coalesce(w.collected_amount, 0)                  as collected_amount,
    w.first_won_date,
    w.first_paid_date,
    w.first_paid_date - c.source_created_date        as days_lead_to_cash,

    -- funnel flags: each stage implies the previous one
    coalesce(d.deals_count, 0) > 0                   as reached_deal,
    coalesce(w.won_deals_count, 0) > 0               as reached_won,
    coalesce(w.collected_amount, 0) > 0              as reached_paid
from contacts as c
left join deals as d on c.contact_id = d.contact_id
left join won as w on c.contact_id = w.contact_id
