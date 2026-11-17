-- One row per Stripe invoice (latest status). Amounts in currency units.
-- Business dates come from metadata: Stripe stamps objects with the real load time.

with source as (

    select * from {{ source('raw', 'raw_stripe_invoices') }}

),

renamed as (

    select
        -- ids
        id                                                       as invoice_id,
        {{ json_text('$.metadata.invoice_external_id') }}        as invoice_external_id,
        {{ json_text('$.metadata.crm_deal_id') }}                as crm_deal_id,      -- empty when billing lacks the CRM ref
        {{ json_text('$.customer') }}                            as customer_id,
        {{ json_text('$.payment_intent') }}                      as payment_intent_id,

        -- status and amounts
        {{ json_text('$.status') }}                              as status,
        upper({{ json_text('$.currency') }})                     as currency,
        {{ cents_to_amount(json_text('$.amount_due')) }}         as amount_due,
        {{ cents_to_amount(json_text('$.amount_paid')) }}        as amount_paid_in_stripe,
        {{ cents_to_amount(json_text('$.amount_remaining')) }}   as amount_remaining,

        -- business dates (simulated)
        try_cast({{ json_text('$.metadata.invoice_date') }} as date) as invoice_date,
        try_cast({{ json_text('$.metadata.due_date') }} as date)     as due_date,

        -- timestamps (UTC, real time in Stripe)
        {{ epoch_to_timestamp(json_text('$.created')) }}                       as created_at_utc,
        {{ epoch_to_timestamp(json_text('$.status_transitions.paid_at')) }}    as paid_at_utc,
        {{ iso_to_timestamp('_loaded_at') }}                                   as loaded_at_utc

    from source

)

select * from renamed
