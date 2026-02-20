# Implementation Plan: Multi-Agent + Test Call + RBAC

## Current DB Schema (Supabase)
- agent_config (1 row, single agent)
- ai_config (1 row, single config)
- campaigns → agent_config
- campaign_leads → campaigns
- encuestas → agent_config
- prompt_templates

## Changes Required

### 1. Database: Multi-agent support
- Modify `ai_config` to add `agent_id` FK → agent_config (1:1 per agent)
- Add RLS + Auth tables for RBAC

### 2. New Tables
- `user_profiles`: extends auth.users with role, created_by
- `user_permissions`: which modules each user can access

### 3. Frontend Changes
- Rename "Voice Agents" → "Crear Agentes" (listing + form)
- New "Llamada Prueba" tab
- New "Admin" / user management views
- Auth context (login, role checking)
- Route protection based on permissions

### 4. Execution Order
1. Install @supabase/supabase-js
2. DB migrations (agent_id on ai_config, user_profiles, user_permissions, RLS)  
3. Create lib/supabase.ts client
4. Create AuthContext
5. Create LoginView
6. Refactor VoiceAgentsView → AgentListView + AgentFormView
7. Create TestCallView
8. Create UserManagementView
9. Update App.tsx with auth, routing, permissions
10. Update types.ts
