-- One row per HubSpot deal (latest version). Includes the associated company and
-- contact ids, read from the associations the extractor stored in the payload.

with source as (

    select * from {{ source('raw', 'raw_hubspot_deals') }}

),

renamed as (

    select
        -- ids
        id                                                              as deal_id,
        {{ json_text('$.properties.external_id') }}                     as external_id,
        {{ json_text('$.associations.companies[0]') }}                  as company_id,
        {{ json_text('$.associations.contacts[0]') }}                   as contact_id,

        -- attributes
        {{ json_text('$.properties.dealname') }}                        as deal_name,
        split_part({{ json_text('$.properties.dealname') }}, ' - ', 1)  as product,
        try_cast({{ json_text('$.properties.amount') }} as decimal(14, 2)) as amount,
        {{ json_text('$.properties.pipeline') }}                        as pipeline,
        {{ json_text('$.properties.dealstage') }}                       as deal_stage,
        {{ json_text('$.properties.sales_rep') }}                       as sales_rep,

        -- business dates (simulated dates live in custom properties, see ADR 0001)
        {{ hubspot_date(json_text('$.properties.deal_created_date')) }} as deal_created_date,
        {{ hubspot_date(json_text('$.properties.closedate')) }}         as close_date,
        {{ hubspot_date(json_text('$.properties.sim_last_moved')) }}    as last_moved_date,

        -- timestamps (UTC)
        {{ iso_to_timestamp(json_text('$.createdAt')) }}                as created_at_utc,
        {{ iso_to_timestamp('updated_at') }}                            as updated_at_utc,
        {{ iso_to_timestamp('_loaded_at') }}                            as loaded_at_utc

    from source

),

final as (

    -- 3. Simple derived flags are fine in staging; anything that joins other tables is not
    select
        *,
        deal_stage in ('closedwon', 'closedlost') as is_closed,
        deal_stage = 'closedwon'                  as is_won
    from renamed

)

select * from final
