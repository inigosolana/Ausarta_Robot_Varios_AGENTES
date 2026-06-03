alter table public.company_yeastar_configs
add column if not exists api_mode text not null default 'pseries';

alter table public.company_yeastar_configs
drop constraint if exists company_yeastar_configs_api_mode_check;

alter table public.company_yeastar_configs
add constraint company_yeastar_configs_api_mode_check
check (api_mode in ('pseries', 'cloud_pbx'));

update public.company_yeastar_configs
set api_mode = case
  when lower(coalesce(api_url, '')) like '%cloud%'
    or lower(coalesce(api_url, '')) like '%yeastarcloud%'
  then 'cloud_pbx'
  else 'pseries'
end
where api_mode is null
   or api_mode not in ('pseries', 'cloud_pbx');
