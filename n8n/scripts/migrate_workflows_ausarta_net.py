#!/usr/bin/env python3
"""
Migra workflows de n8n.ausarta.net: reemplaza IPs/dominios del servidor antiguo
por app.ausarta.net y actualiza plantillas de email Ausarta Robot.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_URL = os.getenv("N8N_API_URL", "https://n8n.ausarta.net").rstrip("/")
API_KEY = os.getenv("N8N_API_KEY", "")
DEFAULT_FRONTEND = "https://app.ausarta.net"
BACKEND = os.getenv("AUSARTA_BACKEND_URL", os.getenv("FRONTEND_URL", DEFAULT_FRONTEND)).rstrip("/")
FRONTEND = os.getenv("FRONTEND_URL", DEFAULT_FRONTEND).rstrip("/")

REPLACEMENTS = [
    ("http://172.19.0.4:8003", BACKEND),
    ("http://172.19.0.4:8001", BACKEND),
    ("http://backend:8003", BACKEND),
    ("http://backend:8001", BACKEND),
    ("http://ausarta-v2-backend:8001", BACKEND),
    ("http://localhost:8003", BACKEND),
    ("http://localhost:8001", BACKEND),
    ("https://app.ausarta.net", FRONTEND),
    ("http://app.ausarta.net", FRONTEND),
    ("http://15.216.15.30:8080", FRONTEND),
    ("http://15.216.15.30", FRONTEND),
    ("https://15.216.15.30", FRONTEND),
    ("http://15.218.15.30:8080", FRONTEND),
    ("https://15.218.15.30", FRONTEND),
    ("http://79.72.57.62:5678", "https://n8n.ausarta.net"),
    ("http://79.72.57.62", FRONTEND),
]

ROOT = Path(__file__).resolve().parents[2]
RECOVERY_TEMPLATE = ROOT / "backend/templates/password_recovery_es.html"


def _api(method: str, path: str, body: dict | None = None) -> dict:
    if not API_KEY:
        raise SystemExit("Falta N8N_API_KEY en el entorno")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=data,
        method=method,
        headers={
            "X-N8N-API-KEY": API_KEY,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def _deep_replace(obj, replacements: list[tuple[str, str]]):
    if isinstance(obj, str):
        out = obj
        for old, new in replacements:
            out = out.replace(old, new)
        return out
    if isinstance(obj, list):
        return [_deep_replace(x, replacements) for x in obj]
    if isinstance(obj, dict):
        return {k: _deep_replace(v, replacements) for k, v in obj.items()}
    return obj


def _n8n_html_expr(html: str, link_expr: str) -> str:
    escaped = (
        html.replace("{{ACTION_LINK}}", link_expr)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )
    return f"={escaped}"


def _recovery_email_html() -> str:
    raw = RECOVERY_TEMPLATE.read_text(encoding="utf-8")
    return _n8n_html_expr(
        raw,
        "{{ $('Supabase_Get_Recovery_Link').item.json.action_link }}",
    )


def _invite_email_html() -> str:
    html = f"""<div style="font-family: Arial, Helvetica, sans-serif; color: #1a1a1a; max-width: 600px; margin: 0 auto; border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden;">
  <div style="background: linear-gradient(135deg, #004a99 0%, #0066cc 100%); padding: 28px 24px; text-align: center;">
    <p style="margin: 0; color: #ffffff; font-size: 22px; font-weight: bold;">Ausarta Robot</p>
    <p style="margin: 8px 0 0; color: #cce0ff; font-size: 14px;">Plataforma de voz empresarial</p>
  </div>
  <div style="padding: 32px 28px; background: #ffffff;">
    <h2 style="color: #004a99; margin: 0 0 16px;">Bienvenido a Ausarta Robot</h2>
    <p>Hola <strong>{{{{ $('Webhook').item.json.body.full_name }}}}</strong>,</p>
    <p>Tu cuenta en <strong>Ausarta Robot Voice AI</strong> ha sido creada correctamente.</p>
    <div style="background: #f0f6ff; border-radius: 8px; padding: 20px; margin: 24px 0;">
      <p style="margin: 0 0 8px; font-weight: bold; color: #004a99;">Credenciales de acceso</p>
      <p style="margin: 4px 0;"><strong>Usuario:</strong> {{{{ $('Webhook').item.json.body.email }}}}</p>
      <p style="margin: 4px 0;"><strong>Contraseña temporal:</strong> {{{{ $('Webhook').item.json.body.password || 'Robot2025!' }}}}</p>
    </div>
    <p><strong>Próximos pasos:</strong></p>
    <ol style="line-height: 1.8;">
      <li>Accede a <a href="{FRONTEND}" style="color: #004a99; font-weight: bold;">{FRONTEND}</a></li>
      <li>Inicia sesión con las credenciales indicadas</li>
      <li>Cambia tu contraseña en Configuración</li>
    </ol>
    <p style="font-size: 13px; color: #666;">¿Dudas? <a href="mailto:clientes@ausarta.es" style="color: #004a99;">clientes@ausarta.es</a></p>
  </div>
</div>"""
    escaped = html.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f"={escaped}"


def _patch_named_nodes(wf: dict) -> list[str]:
    changes: list[str] = []
    name = wf.get("name", "")
    for node in wf.get("nodes", []):
        nname = node.get("name", "")
        params = node.setdefault("parameters", {})

        if nname in ("Enviar_Email_Recuperacion", "Enviar_Email_Bienvenida"):
            opts = params.setdefault("options", {})
            if opts.get("appendAttribution") is not False:
                opts["appendAttribution"] = False
                changes.append("sin pie n8n")

        if name == "Recuperar_Password_Ausarta_v1" and nname == "Supabase_Get_Recovery_Link":
            params["jsonBody"] = (
                "={\n"
                '  "type": "recovery",\n'
                '  "email": "{{ $(\'Webhook_Recovery\').item.json.body.email }}",\n'
                '  "options": {\n'
                f'    "redirect_to": "{{{{ $(\'Webhook_Recovery\').item.json.body.redirect_to || \'{FRONTEND}\' }}}}"\n'
                "  }\n"
                "}"
            )
            changes.append(f"redirect_to → {FRONTEND}")

        if name == "Recuperar_Password_Ausarta_v1" and nname == "Enviar_Email_Recuperacion":
            params["html"] = _recovery_email_html()
            params["subject"] = "Cómo restablecer tu contraseña — Ausarta Robot"
            changes.append("plantilla email recuperación")

        if name == "Invitacion_Usuarios_Ausarta_Robot_v3" and nname == "Enviar_Email_Bienvenida":
            params["html"] = _invite_email_html()
            params["subject"] = "Bienvenido a Ausarta Robot"
            changes.append("plantilla email invitación")

        if nname in ("StartOutboundCall", "NotifyBackendWebhook") and "url" in params:
            old = params["url"]
            if old != f"{BACKEND}/api/calls/outbound" and "calls/outbound" in old:
                params["url"] = f"{BACKEND}/api/calls/outbound"
                changes.append("URL outbound → app.ausarta.net")
            if "webhook/call-result" in old:
                params["url"] = f"{BACKEND}/api/campaigns/webhook/call-result"
                changes.append("URL call-result → app.ausarta.net")

    return changes


def _list_workflows() -> list[dict]:
    out: list[dict] = []
    cursor = None
    while True:
        path = "/api/v1/workflows?limit=100"
        if cursor:
            path += f"&cursor={cursor}"
        batch = _api("GET", path)
        out.extend(batch.get("data", []))
        cursor = batch.get("nextCursor")
        if not cursor:
            break
    return out


def _update_workflow(wf_id: str, wf: dict) -> dict:
    payload = {
        "name": wf["name"],
        "nodes": wf["nodes"],
        "connections": wf["connections"],
        "settings": wf.get("settings", {}),
    }
    return _api("PUT", f"/api/v1/workflows/{wf_id}", payload)


def main() -> int:
    workflows = _list_workflows()
    print(f"Instancia: {API_URL} — {len(workflows)} workflows")

    updated = 0
    for meta in workflows:
        wf_id = meta["id"]
        wf = _api("GET", f"/api/v1/workflows/{wf_id}")
        before = json.dumps(wf)
        wf = _deep_replace(wf, REPLACEMENTS)
        patches = _patch_named_nodes(wf)
        after = json.dumps(wf)

        if before == after and not patches:
            continue

        _update_workflow(wf_id, wf)
        updated += 1
        extra = f" ({', '.join(patches)})" if patches else ""
        print(f"  ✓ {wf['name']}{extra}")

    print(f"\nActualizados: {updated}/{len(workflows)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print(f"Error HTTP n8n: {exc.code} {exc.read().decode()[:300]}", file=sys.stderr)
        raise SystemExit(1)
