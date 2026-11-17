-- One row per HubSpot contact. Same rows as raw: the 2 sample contacts HubSpot
-- creates are kept here and flagged with has_external_id = false.

with source as (

    select * from {{ source('raw', 'raw_hubspot_contacts') }}

),

renamed as (

    select
        -- ids
        id                                                                as contact_id,
        {{ json_text('$.properties.external_id') }}                       as external_id,
        {{ json_text('$.associations.companies[0]') }}                    as company_id,

        -- attributes
        {{ json_text('$.properties.firstname') }}                         as first_name,
        {{ json_text('$.properties.lastname') }}                          as last_name,
        lower({{ json_text('$.properties.email') }})                      as email,
        {{ json_text('$.properties.lead_source') }}                       as lead_source,
        {{ json_text('$.properties.lifecyclestage') }}                    as lifecycle_stage,

        -- business date (simulated)
        {{ hubspot_date(json_text('$.properties.source_created_date')) }} as source_created_date,

        -- timestamps (UTC)
        {{ iso_to_timestamp(json_text('$.createdAt')) }}                  as created_at_utc,
        {{ iso_to_timestamp('updated_at') }}                              as updated_at_utc,
        {{ iso_to_timestamp('_loaded_at') }}                              as loaded_at_utc

    from source

),

final as (

    select
        *,
        external_id is not null as has_external_id
    from renamed

)

select * from final
