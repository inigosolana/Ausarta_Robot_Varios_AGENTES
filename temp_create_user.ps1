$body = @{
    email = "instalaciones@ausarta.es"
    password = "AureaT08."
} | ConvertTo-Json

$headers = @{
    apikey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFmcnJ4ZWlidHJ3amFpcW1oeXR1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE0MTA4NjAsImV4cCI6MjA4Njk4Njg2MH0.9k0C1EGjxAG47DJZx1jAweODFiaXenrjirYz91ZNpWs"
    "Content-Type" = "application/json"
}

$result = Invoke-RestMethod -Uri "https://afrrxeibtrwjaiqmhytu.supabase.co/auth/v1/signup" -Method Post -Headers $headers -Body $body
$result | ConvertTo-Json -Depth 5
