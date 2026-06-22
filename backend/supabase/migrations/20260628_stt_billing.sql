-- STT audio seconds en billing + categoría mensual
ALTER TABLE public.tenant_usage_events
    DROP CONSTRAINT IF EXISTS tenant_usage_events_event_type_chk;

ALTER TABLE public.tenant_usage_events
    ADD CONSTRAINT tenant_usage_events_event_type_chk CHECK (
        event_type IN ('llm_tokens', 'tts_characters', 'stt_audio_seconds', 'telephony_seconds')
    );

ALTER TABLE public.tenant_usage_monthly
    DROP CONSTRAINT IF EXISTS tenant_usage_monthly_category_chk;

ALTER TABLE public.tenant_usage_monthly
    ADD CONSTRAINT tenant_usage_monthly_category_chk CHECK (
        category IN (
            'llm_prompt_tokens',
            'llm_completion_tokens',
            'tts_characters',
            'stt_audio_seconds',
            'telephony_seconds'
        )
    );
