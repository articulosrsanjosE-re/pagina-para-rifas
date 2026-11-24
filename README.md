# San José — Sistema de rifas

## Probar en Windows
Instala Python 3.12. Abre PowerShell dentro de esta carpeta:

```
python -m pip install -r requirements.txt
$env:SECRET_KEY = (python -c "import secrets; print(secrets.token_hex(32))")
$env:ADMIN_PASSWORD = 'REEMPLAZAR-CON-UNA-CLAVE-PRIVADA'
$env:PUBLIC_URL = 'http://localhost:8000'
$env:HTTPS = '0'
python app.py
```
Abre http://localhost:8000/admin y http://localhost:8000/ . El QR local no funciona desde otros teléfonos. Los primeros 1000 códigos se crean al iniciar una base vacía. No uses la contraseña de ejemplo.

## Publicar en internet
Usa un alojamiento de contenedores Docker con HTTPS y disco persistente (por ejemplo un servicio web de Render con disco de pago, o un VPS). Sube esta carpeta a un repositorio privado y conecta el servicio Docker. Puerto 8000. Monta un disco persistente en /data. Configura variables SECRET_KEY (valor aleatorio de 64 caracteres hexadecimales), ADMIN_PASSWORD (privada, mínimo 12 caracteres), PUBLIC_URL (URL HTTPS pública definitiva, sin barra final), HTTPS=1, DB_PATH=/data/rifa.sqlite. No subas secretos al repositorio. Conserva SECRET_KEY entre reinicios. La contraseña inicial solo se utiliza al crear la base. Configura limitación de solicitudes en el proxy, especialmente POST /admin y POST /, y HTTPS obligatorio antes de abrir al público. No uses varias réplicas con discos independientes. El costo depende del proveedor.

## Uso
1. Entra en /admin. Cambia la contraseña si deseas.
2. Configura título y cierre. Imprime las 1000 tarjetas disponibles o genera un lote adicional. Selecciona papel carta y escala 100%; desactiva encabezados del navegador. No entregues dos copias del mismo código.
3. Prueba el QR desde un teléfono con datos móviles antes de imprimir el lote definitivo. El QR apunta siempre a PUBLIC_URL.
4. Los clientes registran su código, nombre, dirección, teléfono y país. Cada código solo se consume una vez, incluso con solicitudes simultáneas.
5. Exporta CSV y respalda la base de datos. Para abrir en Excel usa UTF-8 y columnas de código/teléfono como texto.
6. Cierra inscripciones, abre la ruleta, escribe el premio y gira. El servidor registra el ganador antes de la animación. Revisa historial si se interrumpe la conexión. Cada código puede ganar una vez; una persona con varios códigos puede ganar varias veces. Para el siguiente premio recarga la ruleta. No abras dos sorteos simultáneamente.

## Operación y privacidad
La base persiste en el disco; realiza copias con la API backup de SQLite o con el servicio detenido. Protege las copias y el CSV. Define bases legales, elegibilidad, premios, fecha, aviso de privacidad completo, contacto y plazo de conservación antes de publicar; verifica requisitos de promociones en los tres países. No publiques teléfonos ni direcciones. Esta versión gestiona una campaña por base de datos. Para una nueva campaña conserva una copia privada de la anterior y crea una base nueva; no reutilices tarjetas antiguas. No hay recuperación automática de contraseña: el operador del servidor debe restablecerla en la base con un hash Werkzeug y cambiar version para invalidar sesiones. No se ha publicado ningún sitio desde este chat.
