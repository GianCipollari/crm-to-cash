-- One row per HubSpot company. Mirrors raw_hubspot_companies: same grain, no filters,
-- only renamed, typed and cleaned columns. Business logic waits for intermediate.

with source as (

    -- 1. Read the raw table declared in sources.yml
    select * from {{ source('raw', 'raw_hubspot_companies') }}

),

renamed as (

    -- 2. Pull each field out of the JSON payload and give it a clear name and type
    select
        -- ids
        id                                                   as company_id,     -- HubSpot internal id
        {{ json_text('$.properties.external_id') }}          as external_id,    -- our CMP-xxxx id

        -- attributes
        {{ json_text('$.properties.name') }}                 as company_name,
        lower({{ json_text('$.properties.domain') }})        as domain,
        {{ json_text('$.properties.country') }}              as country,
        {{ json_text('$.properties.tax_id') }}               as tax_id,

        -- timestamps (UTC)
        {{ iso_to_timestamp(json_text('$.createdAt')) }}     as created_at_utc,  -- load time in HubSpot
        {{ iso_to_timestamp('updated_at') }}                 as updated_at_utc,
        {{ iso_to_timestamp('_loaded_at') }}                 as loaded_at_utc

    from source

)

select * from renamed
