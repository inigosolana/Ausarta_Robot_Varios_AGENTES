import json
import os

mapping = {
    "MkglONaefdeNTLrm": "Invitacion_Usuarios_Ausarta_Robot_v3.json",
    "3cLVhxdaKFTer7Ht": "Orquestador_de_Campanas___Ausarta_NUEVO___Active.json",
    "c1GO5ZJVQEkxgaLE": "Orquestador_de_Campanas___Ausarta_Voice_AI_Force_Chat.json",
    "zTIva1ME01dBf0im": "Recuperar_Password_Ausarta_v1.json",
    "FbXAQlUVAxAwDxOm": "Ausarta_DevOps___Error_Monitor_AI.json",
    "ja9QYHNbqS3grvKJ": "Procesamiento_de_Transcripciones_Ausarta_Voice_AI.json"
}

output_files = {
    "MkglONaefdeNTLrm": r"C:\Users\inigo2.solana\.gemini\antigravity\brain\4911cfea-d6d7-4a57-9687-40ac8c481a33\.system_generated\steps\740\output.txt",
    "3cLVhxdaKFTer7Ht": r"C:\Users\inigo2.solana\.gemini\antigravity\brain\4911cfea-d6d7-4a57-9687-40ac8c481a33\.system_generated\steps\741\output.txt",
    "c1GO5ZJVQEkxgaLE": r"C:\Users\inigo2.solana\.gemini\antigravity\brain\4911cfea-d6d7-4a57-9687-40ac8c481a33\.system_generated\steps\742\output.txt",
    "zTIva1ME01dBf0im": r"C:\Users\inigo2.solana\.gemini\antigravity\brain\4911cfea-d6d7-4a57-9687-40ac8c481a33\.system_generated\steps\743\output.txt",
    "FbXAQlUVAxAwDxOm": r"C:\Users\inigo2.solana\.gemini\antigravity\brain\4911cfea-d6d7-4a57-9687-40ac8c481a33\.system_generated\steps\744\output.txt",
    "ja9QYHNbqS3grvKJ": r"C:\Users\inigo2.solana\.gemini\antigravity\brain\4911cfea-d6d7-4a57-9687-40ac8c481a33\.system_generated\steps\745\output.txt"
}

target_dir = r"c:\Users\inigo2.solana\Ausarta_Robot_Varios_AGENTES\n8n\workflows"

for workflow_id, output_path in output_files.items():
    with open(output_path, 'r', encoding='utf-8') as f:
        # Strip line numbers if they were added (though view_file says it adds them, 
        # let's assume raw content for now or handle it)
        content = f.read()
        # The content in output.txt from view_file includes line numbers like "1: {"
        # I need to strip them.
        lines = content.splitlines()
        clean_lines = []
        for line in lines:
            if ": " in line:
                clean_lines.append(line.split(": ", 1)[1])
            else:
                clean_lines.append(line)
        
        json_data = json.loads("\n".join(clean_lines))
        workflow_data = json_data['data']
        
        target_file = os.path.join(target_dir, mapping[workflow_id])
        with open(target_file, 'w', encoding='utf-8') as tf:
            json.dump(workflow_data, tf, indent=2, ensure_ascii=False)
        print(f"Updated {target_file}")
