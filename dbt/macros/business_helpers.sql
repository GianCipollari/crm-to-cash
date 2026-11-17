{#
  "Today" for the business logic (overdue invoices). Pass a fixed date to make a
  run reproducible:  dbt build --vars "as_of_date: 2026-11-13"
#}
{% macro as_of_date() -%}
    {%- if var('as_of_date', none) -%}
        cast('{{ var("as_of_date") }}' as date)
    {%- else -%}
        current_date
    {%- endif -%}
{%- endmacro %}


{#
  Company name in a comparable form: no accents, lower case, no punctuation and
  no legal form, so "Atlántico Farma Ltda." and "ATLANTICO FARMA LTDA" are equal.
#}
{% macro normalize_company_name(expr) -%}
    trim(regexp_replace(
        regexp_replace(lower(strip_accents({{ expr }})), '[^a-z0-9 ]', '', 'g'),
        '\s+(sa de cv|sa|srl|sas|ltda)$', ''
    ))
{%- endmacro %}
