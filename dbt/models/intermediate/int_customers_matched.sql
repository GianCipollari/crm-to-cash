-- One row per Stripe customer, linked to its HubSpot company.
-- Three passes, each only for customers the previous pass left unmatched:
--   1. external_id     : the CRM id stored in Stripe metadata
--   2. email_domain    : billing email domain = company domain
--   3. normalized_name : names equal after removing accents, punctuation and legal form
-- Customers no pass can resolve stay with match_method = 'unmatched'.

with customers as (

    select * from {{ ref('stg_stripe__customers') }}

),

companies as (

    select * from {{ ref('stg_hubspot__companies') }}
    where external_id is not null

),

by_external_id as (

    select cu.customer_id, co.company_id, 'external_id' as match_method
    from customers as cu
    inner join companies as co on cu.crm_company_id = co.external_id

),

by_domain as (

    select cu.customer_id, co.company_id, 'email_domain' as match_method
    from customers as cu
    inner join companies as co on cu.email_domain = co.domain
    where cu.customer_id not in (select customer_id from by_external_id)

),

by_name as (

    select cu.customer_id, co.company_id, 'normalized_name' as match_method
    from customers as cu
    inner join companies as co
        on {{ normalize_company_name('cu.customer_name') }} = {{ normalize_company_name('co.company_name') }}
    where cu.customer_id not in (select customer_id from by_external_id)
      and cu.customer_id not in (select customer_id from by_domain)

),

matches as (

    select * from by_external_id
    union all
    select * from by_domain
    union all
    select * from by_name

)

select
    cu.customer_id,
    cu.customer_name,
    cu.email_domain,
    cu.crm_company_id                             as crm_company_id_in_stripe,
    m.company_id,
    co.external_id                                as company_external_id,
    co.company_name,
    coalesce(m.match_method, 'unmatched')         as match_method,
    cu.customer_name is distinct from co.company_name as name_differs  -- surfaces name variants
from customers as cu
left join matches as m on cu.customer_id = m.customer_id
left join companies as co on m.company_id = co.company_id
