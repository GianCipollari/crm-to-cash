-- One row per data problem detected, in the same vocabulary as the anomaly manifest
-- (issue_type, object_type, external_id, related_deal_id), so tests can compare both.
-- Answers business question 4: how reliable is the CRM data.

with reconciliation as (

    select * from {{ ref('fct_deal_reconciliation') }}

),

customers as (

    select * from {{ ref('int_customers_matched') }}

),

deal_issues as (

    select
        case reconciliation_status
            when 'duplicate'         then 'duplicate_deal'
            when 'missing_invoice'   then 'missing_invoice'
            when 'unpaid_overdue'    then 'unpaid_invoice'
            when 'partial_payment'   then 'partial_payment'
            when 'amount_mismatch'   then 'amount_mismatch'
            when 'late_stage_update' then 'late_stage_update'
            when 'refunded'          then 'refund'
        end                                                   as issue_type,
        'deal'                                                as object_type,
        external_id,
        coalesce(duplicate_of_external_id, external_id)       as related_deal_id,
        case when reconciliation_status = 'duplicate' then deal_amount
             else gap_amount end                              as amount_at_risk,
        'Deal ' || external_id || ': ' || reconciliation_status as detail
    from reconciliation
    where reconciliation_status not in ('reconciled', 'not_yet_due', 'pending_invoice')

),

customer_issues as (

    select
        'name_variant'                                        as issue_type,
        'customer'                                            as object_type,
        company_external_id                                   as external_id,
        null                                                  as related_deal_id,
        null                                                  as amount_at_risk,
        'CRM name "' || company_name || '" billed as "' || customer_name || '"' as detail
    from customers
    where match_method <> 'unmatched' and name_differs

    union all

    select
        'missing_external_id',
        'customer',
        company_external_id,
        null,
        null,
        'Billing customer ' || customer_id || ' has no CRM id (matched by ' || match_method || ')'
    from customers
    where match_method <> 'unmatched' and crm_company_id_in_stripe is null

    union all

    select
        'unmatched_customer',
        'customer',
        customer_id,
        null,
        null,
        'Billing customer ' || customer_id || ' matches no CRM company'
    from customers
    where match_method = 'unmatched'

),

contact_issues as (

    select
        'contact_without_external_id'                         as issue_type,
        'contact'                                             as object_type,
        contact_id                                            as external_id,
        null                                                  as related_deal_id,
        null                                                  as amount_at_risk,
        'Contact ' || coalesce(email, contact_id) || ' was not created by the pipeline' as detail
    from {{ ref('stg_hubspot__contacts') }}
    where not has_external_id

),

all_issues as (

    select * from deal_issues
    union all
    select * from customer_issues
    union all
    select * from contact_issues

)

select
    md5(issue_type || '|' || external_id)   as issue_id,
    issue_type,
    object_type,
    external_id,
    related_deal_id,
    cast(amount_at_risk as decimal(14, 2))  as amount_at_risk,
    detail,
    {{ as_of_date() }}                      as detected_on
from all_issues
