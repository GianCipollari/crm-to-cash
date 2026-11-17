-- One row per Stripe refund. Needed for net collected amounts and to detect refunds.

with source as (

    select * from {{ source('raw', 'raw_stripe_refunds') }}

),

renamed as (

    select
        -- ids
        id                                                        as refund_id,
        {{ json_text('$.payment_intent') }}                       as payment_intent_id,
        {{ json_text('$.charge') }}                               as charge_id,
        {{ json_text('$.metadata.payment_external_id') }}         as payment_external_id,

        -- status and amount
        {{ json_text('$.status') }}                               as status,
        upper({{ json_text('$.currency') }})                      as currency,
        {{ cents_to_amount(json_text('$.amount')) }}              as amount,

        -- business date (simulated)
        try_cast({{ json_text('$.metadata.refunded_at') }} as date) as refunded_date,

        -- timestamps (UTC)
        {{ epoch_to_timestamp(json_text('$.created')) }}          as created_at_utc,
        {{ iso_to_timestamp('_loaded_at') }}                      as loaded_at_utc

    from source

)

select * from renamed
