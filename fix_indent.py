import sys

with open('backend/agent.py', 'r', encoding='utf-8') as f:
    text = f.read()

finally_start = "            # Guardados post-llamada deben ir al mismo backend accesible desde este worker"
finally_end = "        else:\n            logger.info(f\"--- 🏁 FIN DE SESIÓN DUPLICADA"

start_idx = text.find(finally_start)
end_idx = text.find(finally_end)

if start_idx != -1 and end_idx != -1:
    before = text[:start_idx]
    middle = text[start_idx:end_idx]
    after = text[end_idx:]
    
    middle_lines = middle.split('\n')
    indented_middle = '\n'.join(['    ' + line if line.strip() else line for line in middle_lines])
    
    wrapped_start = "            try:\n"
    wrapped_end = "            except Exception as fatal_post:\n                logger.error(f\"🚨 [{job_id}] EXCEPCIÓN FATAL NO CAPTURADA en post-procesamiento (finally): {fatal_post}\")\n"
    
    text = before + wrapped_start + indented_middle + wrapped_end + after

    with open('backend/agent.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print("Agent block indented successfully.")
else:
    print("Could not find blocks.")
