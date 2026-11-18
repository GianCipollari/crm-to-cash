-- One row per data problem detected, in the same vocabulary as the anomaly manifest
-- (issue_type, object_type, external_id, related_deal_id), so tests can compare both.
-- Answers business question 4: how reliable is the CRM data.

with reconciliation as (

    select * from {{ ref('fct_deal_reconciliation') }}

),

customers as (

    select * from {{ ref('int_customers_matched') }}

),

deal_checks as (

    -- Each problem has its own rule, so one deal can show several problems at once
    -- (for example an unpaid invoice that also carries an unrecorded discount).
    -- reconciliation_status in the fact keeps only the main one.
    select
        *,
        is_duplicate                                                        as has_duplicate_deal,
        not is_duplicate and reconciliation_status = 'missing_invoice'      as has_missing_invoice,
        not is_duplicate and reconciliation_status = 'unpaid_overdue'       as has_unpaid_invoice,
        not is_duplicate and amount_collected > 0
            and amount_collected < invoice_amount                           as has_partial_payment,
        not is_duplicate and invoice_id is not null
            and abs(amount_difference) > {{ var('amount_tolerance') }} * deal_amount as has_amount_mismatch,
        not is_duplicate and last_paid_date < close_date                    as has_late_stage_update,
        not is_duplicate and amount_refunded > 0                            as has_refund
    from reconciliation

),

{#- issue type -> amount at risk for that issue; Jinja writes one select per check -#}
{%- set checks = {
    'duplicate_deal':    'deal_amount',
    'missing_invoice':   'gap_amount',
    'unpaid_invoice':    'gap_amount',
    'partial_payment':   'gap_amount',
    'amount_mismatch':   'abs(amount_difference)',
    'late_stage_update': '0',
    'refund':            'amount_refunded',
} %}

deal_issues as (

    {% for issue, amount in checks.items() %}
    select
        '{{ issue }}'                                         as issue_type,
        'deal'                                                as object_type,
        external_id,
        coalesce(duplicate_of_external_id, external_id)       as related_deal_id,
        {{ amount }}                                          as amount_at_risk,
        'Deal ' || external_id || ' (status: ' || reconciliation_status || ')' as detail
    from deal_checks
    where has_{{ issue }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}

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
