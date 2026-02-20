# Frontend Dockerfile
FROM node:20-alpine AS builder

WORKDIR /app

# Copiar package files
COPY package*.json ./

# Instalar dependencias
RUN npm install

# Copiar el resto del código
COPY . .

# Build args para que Vite inyecte las variables en tiempo de build
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ARG VITE_API_URL

ENV VITE_SUPABASE_URL=${VITE_SUPABASE_URL}
ENV VITE_SUPABASE_ANON_KEY=${VITE_SUPABASE_ANON_KEY}
ENV VITE_API_URL=${VITE_API_URL}

# Build de producción
RUN npm run build

# Stage de producción con nginx
FROM nginx:alpine

# Copiar archivos build
COPY --from=builder /app/dist /usr/share/nginx/html

# Copiar configuración de nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Exponer puerto 80
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
