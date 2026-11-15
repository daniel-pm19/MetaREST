# Infraestructura de Nestor

## Local

Configura `backend/.env` según `docs/API.md`. Con Docker Desktop/motor Docker activo,
desde la raíz:

```powershell
docker compose --env-file backend/.env -f infra/docker-compose.yml up --build -d --wait
```

Frontend conectado al backend: `http://localhost:8080`. Backend:
`http://127.0.0.1:8000/docs`. Demo: `http://127.0.0.1:8001/docs`.
Dentro de Docker registra la URL de la demo como `http://sut-demo:8001`; una URL
`localhost` dentro del backend apuntaría al propio contenedor backend.

Mongo no publica puertos; los datos y el modelo fastembed usan volúmenes. La primera
ejecución con LLM necesita la API key y descargar el modelo de embeddings. El
frontend se construye con `VITE_API_URL=/api`, sin cambiar el código de Isaac.

## Producción preparada, pendiente de ejecución

`docker-compose.prod.yml`, Nginx HTTPS, `deploy.yml` y `scripts/backup.sh` son recetas
para el servidor. No crean recursos AWS, dominio, certificados ni credenciales.
No se han desplegado desde este chat.

Requisitos externos:

1. EC2 Ubuntu con Docker Compose v2, disco persistente y /opt/metarest propiedad
   del usuario de despliegue. Grupo de seguridad: 80/443 públicos y SSH solo desde
   las IPs autorizadas (o un mecanismo de acceso restringido al runner).
2. DNS `DOMAIN` apuntando a esa instancia. Instalar certbot y emitir el certificado
   inicial con `certbot certonly --standalone -d <dominio>` antes de arrancar Nginx.
   Para renovar con Nginx activo: webroot `/opt/metarest/infra/certbot`, timer de
   certbot y reload del contenedor frontend después de renovar.
3. Copiar estas recetas a `/opt/metarest/infra` y configurar `/opt/metarest/.env`
   (permisos 600): `DOMAIN`, `GHCR_OWNER`, `MONGO_ROOT_USER`, `MONGO_ROOT_PASSWORD`,
   `MONGODB_URI` autenticada hacia `mongo:27017`, `JWT_SECRET`, `ADMIN_EMAIL`,
   `ADMIN_PASSWORD`, y la API key elegida. URI encodea caracteres especiales de la
   contraseña. Configurar un usuario Mongo de aplicación con permisos mínimos;
   para `decisions`/`audit_log`, permitir find/insert y prohibir update/delete.
4. GHCR accesible desde el host; si las imágenes son privadas, configurar allí un
   token de solo lectura de paquetes. Secrets de Actions: `EC2_SSH_KEY`,
   `EC2_KNOWN_HOSTS` verificado por un canal de confianza y `EC2_SSH_TARGET`
   (`usuario@host`). No se desactiva la comprobación de identidad del host.
5. CI ejecuta pruebas y build. Solo un CI exitoso de push a `main` activa Deploy;
   las imágenes se etiquetan por commit y el host usa esa misma versión.

Backup: instancia con rol IAM de escritura limitado al prefijo S3 `metarest/`, AWS
CLI en el host y `BACKUP_BUCKET` configurado. Programar `scripts/backup.sh` una vez
al día y aplicar la regla de `scripts/s3-lifecycle.json` para retención de 7 días.
La regla elimina objetos expirados: revisar bucket/prefijo antes de aplicarla.
Verificar restauración en una base separada antes de considerar cerrado el backup.
CloudWatch requiere agente, permisos y alarmas: sigue pendiente de configurar.

## Verificación

Se puede ejecutar `docker compose ... config --quiet` sin motor Docker para validar
los manifiestos. Esto no comprueba que las imágenes construyan o que los servicios
arranquen. La CI y el despliegue se consideran pendientes hasta que corran en
GitHub y EC2 respectivamente. No se añadieron claves ni valores reales al repo.
