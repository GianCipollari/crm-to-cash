-- One row per CRM company created by the pipeline, with its billing customer (if any).
-- The shared "who" for the reconciliation and funnel facts.

with companies as (

    select * from {{ ref('stg_hubspot__companies') }}
    where external_id is not null

),

billing as (

    -- one billing customer per company; if there were two, keep the first created
    select
        company_id,
        arg_min(customer_id, customer_id)    as stripe_customer_id,
        arg_min(match_method, customer_id)   as match_method,
        bool_or(name_differs)                as billing_name_differs,
        count(*)                             as billing_customers_count
    from {{ ref('int_customers_matched') }}
    where company_id is not null
    group by 1

),

won as (

    select
        company_id,
        count(*)            as won_deals_count,
        sum(deal_amount)    as won_amount,
        sum(net_collected)  as collected_amount,
        min(close_date)     as first_won_date
    from {{ ref('fct_deal_reconciliation') }}
    where not is_duplicate
    group by 1

)

select
    c.company_id,
    c.external_id,
    c.company_name,
    c.domain,
    c.country,
    b.stripe_customer_id,
    b.match_method,
    coalesce(b.billing_name_differs, false)    as billing_name_differs,
    coalesce(b.billing_customers_count, 0)     as billing_customers_count,
    b.stripe_customer_id is not null           as is_billed_customer,
    coalesce(w.won_deals_count, 0)             as won_deals_count,
    coalesce(w.won_amount, 0)                  as won_amount,
    coalesce(w.collected_amount, 0)            as collected_amount,
    w.first_won_date
from companies as c
left join billing as b on c.company_id = b.company_id
left join won as w on c.company_id = w.company_id
