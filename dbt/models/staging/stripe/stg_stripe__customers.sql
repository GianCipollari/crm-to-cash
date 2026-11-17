-- One row per Stripe customer. `crm_company_id` is empty for customers created
-- without the CRM id (planted on purpose): intermediate matches them by domain.

with source as (

    select * from {{ source('raw', 'raw_stripe_customers') }}

),

renamed as (

    select
        -- ids
        id                                                   as customer_id,
        {{ json_text('$.metadata.crm_company_id') }}         as crm_company_id,

        -- attributes
        {{ json_text('$.name') }}                            as customer_name,
        lower({{ json_text('$.email') }})                    as email,
        split_part(lower({{ json_text('$.email') }}), '@', 2) as email_domain,

        -- timestamps (UTC)
        {{ epoch_to_timestamp(json_text('$.created')) }}     as created_at_utc,
        {{ iso_to_timestamp('_loaded_at') }}                 as loaded_at_utc

    from source

)

select * from renamed
