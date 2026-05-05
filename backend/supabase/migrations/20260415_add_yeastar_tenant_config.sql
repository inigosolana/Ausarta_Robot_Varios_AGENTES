-- Add Yeastar P-Series configuration columns to the empresas table
ALTER TABLE empresas 
ADD COLUMN IF NOT EXISTS yeastar_pbx_url VARCHAR(255),
ADD COLUMN IF NOT EXISTS yeastar_client_id VARCHAR(255),
ADD COLUMN IF NOT EXISTS yeastar_client_secret VARCHAR(255);
