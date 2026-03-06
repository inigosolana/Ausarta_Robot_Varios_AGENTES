import re

with open('backend/agent.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Identity validation
id_validation = """
    # 3. Validación de Identidad Temprana Crítica
    if not str(survey_id).isdigit() or str(survey_id) == "0":
        logger.error(f"🚨🚨🚨 [{job_id}] Identidad inválida o corrupta: survey_id='{survey_id}'. Abortando worker.")
        ctx.reject()
        return

    # --- PASO 1.5: Validar Sello Multi-Tenant ANTES de conectar ---"""
text = text.replace("    # --- PASO 1.5: Validar Sello Multi-Tenant ANTES de conectar ---", id_validation)

# 2. Transcript Filter
transcript_old = """                            if m.content and m.role in ("user", "assistant"):
                                raw_messages.append({"role": m.role, "content": m.content})
                                role_label = "Cliente" if m.role == "user" else "Agente"
                                transcript += f"{role_label}: {m.content}\\n\""""""
transcript_new = """                            content = (m.content or "").strip()
                            # 4. Robustez: Filtrar mensajes vacíos o ruidos cortos
                            if content and len(content) > 1 and m.role in ("user", "assistant"):
                                raw_messages.append({"role": m.role, "content": content})
                                role_label = "Cliente" if m.role == "user" else "Agente"
                                transcript += f"{role_label}: {content}\\n\""""""
text = text.replace(transcript_old, transcript_new)

# 3. Wrap finally
finally_start = "            # Guardados post-llamada deben ir al mismo backend accesible desde este worker"
finally_end = "        else:\n            logger.info("

start_idx = text.find(finally_start)
end_idx = text.find(finally_end)

if start_idx != -1 and end_idx != -1:
    before = text[:start_idx]
    middle = text[start_idx:end_idx]
    after = text[end_idx:]
    
    # Indent middle string
    middle_lines = middle.split('\\n')
    indented_middle = '\\n'.join(['    ' + line if line.strip() else line for line in middle_lines])
    
    wrapped = f"            try:\\n    {indented_middle}            except Exception as fatal_post:\\n                logger.error(f\\"🚨 [{{job_id}}] EXCEPCIÓN FATAL NO CAPTURADA en post-procesamiento (finally): {{fatal_post}}\\")\\n"
    
    text = before + wrapped + after

with open('backend/agent.py', 'w', encoding='utf-8') as f:
    f.write(text)
