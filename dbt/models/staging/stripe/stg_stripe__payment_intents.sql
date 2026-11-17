-- One row per Stripe payment intent (a payment attempt).
-- Two kinds exist in this project:
--   invoice_payment: created by paying an invoice; Stripe links it with `invoice`
--   standalone:      a partial payment; the invoice is referenced only in metadata

with source as (

    select * from {{ source('raw', 'raw_stripe_payment_intents') }}

),

renamed as (

    select
        -- ids
        id                                                       as payment_intent_id,
        {{ json_text('$.customer') }}                            as customer_id,
        {{ json_text('$.invoice') }}                             as invoice_id,
        {{ json_text('$.metadata.invoice_external_id') }}        as invoice_external_id,
        {{ json_text('$.metadata.payment_external_id') }}        as payment_external_id,

        -- status and amounts
        {{ json_text('$.status') }}                              as status,
        upper({{ json_text('$.currency') }})                     as currency,
        {{ cents_to_amount(json_text('$.amount')) }}             as amount,
        {{ cents_to_amount(json_text('$.amount_received')) }}    as amount_received,

        -- business date (simulated)
        try_cast({{ json_text('$.metadata.paid_at') }} as date)  as paid_date,

        -- timestamps (UTC)
        {{ epoch_to_timestamp(json_text('$.created')) }}         as created_at_utc,
        {{ iso_to_timestamp('_loaded_at') }}                     as loaded_at_utc

    from source

),

final as (

    select
        *,
        case when invoice_id is not null then 'invoice_payment' else 'standalone' end as payment_kind
    from renamed

)

select * from final
