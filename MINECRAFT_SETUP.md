# 🎮 Configuración de Minecraft para el Bot de Discord

## 📋 Requisitos Previos

1. **Servidor de Minecraft** funcionando (Java Edition)
2. **RCON habilitado** en el servidor
3. **Variables de entorno** configuradas
4. **Acceso al archivo de logs** del servidor (para chat bridge)
5. **Fixie Socks** configurado en Heroku (para IP estática)

## ⚙️ Configuración del Servidor de Minecraft

### 1. Habilitar RCON en server.properties

Edita el archivo `server.properties` de tu servidor de Minecraft:

```properties
# Habilitar RCON (OBLIGATORIO)
enable-rcon=true
rcon.port=25575
rcon.password=tu_contraseña_segura_aqui

# Query opcional (puede estar en false)
enable-query=false
```

### 2. Configurar Firewall/Azure para IP Estática

Si tu servidor está en Azure, configura las reglas de firewall para permitir:
- **Puerto 25565** (servidor Minecraft) desde la IP de Fixie Socks
- **Puerto 25575** (RCON) desde la IP de Fixie Socks

### 3. Reiniciar el Servidor

Después de modificar `server.properties`, reinicia tu servidor de Minecraft.

## 🌐 Configuración de IP Estática con Fixie Socks

### 1. Agregar Fixie Socks a Heroku

```bash
# Agregar el add-on de Fixie Socks a tu app de Heroku
heroku addons:create fixie-socks:starter -a tu-app-name
```

### 2. Obtener la IP Estática

```bash
# Ver tu IP estática
heroku addons:info fixie-socks -a tu-app-name
```

### 3. Configurar Firewall de Azure

Agrega la IP de Fixie Socks a las reglas de tu firewall en Azure para los puertos:
- `25565` (Minecraft)
- `25575` (RCON)

## 🔧 Variables de Entorno

Configura estas variables de entorno en tu sistema o archivo `.env`:

```bash
# Bot de Discord
DISCORD_TOKEN=tu_token_de_discord_aqui

# Información del servidor
MC_SERVER_IP=tu_ip_publica_del_servidor        # IP pública de tu servidor en Azure
MC_SERVER_PORT=25565                           # Puerto del servidor (por defecto: 25565)
MC_RCON_PORT=25575                             # Puerto RCON (por defecto: 25575)
MC_RCON_PASSWORD=tu_contraseña_rcon            # ¡OBLIGATORIO para comandos RCON!

# Configuración del Chat Bridge (opcional)
MC_CHAT_CHANNEL_ID=123456789012345678          # ID del canal de Discord para el chat
MC_LOG_PATH=/ruta/al/servidor/logs/latest.log  # Ruta al archivo de logs

# IP Estática (se configura automáticamente por Heroku)
FIXIE_SOCKS_HOST=user:pass@host:port           # Configurado automáticamente por Fixie Socks
```

### Ejemplo para servidor en Azure:
```bash
DISCORD_TOKEN=tu_token_aqui
MC_SERVER_IP=20.123.456.789                   # IP pública de Azure
MC_SERVER_PORT=25565
MC_RCON_PORT=25575
MC_RCON_PASSWORD=2Pgl9rSWq!7tE0
MC_CHAT_CHANNEL_ID=123456789012345678
# FIXIE_SOCKS_HOST se configura automáticamente
```

## 🎯 Comandos Disponibles

Una vez configurado, tendrás acceso a estos comandos slash:

### 📊 Información del Servidor
- `/mcstatus` - Muestra el estado del servidor (online/offline, jugadores, latencia)
- `/mcplayers` - Lista detallada de jugadores online
- `/mcconfig` - Muestra la configuración actual del bot (incluyendo IP estática)

### 🔧 Administración (Solo Administradores)
- `/mccommand <comando>` - Ejecuta cualquier comando del servidor
- `/mcwhitelist <acción> [jugador]` - Gestiona la whitelist
- `/mckick <jugador> [razón]` - Expulsa a un jugador

### 🌉 Chat Bridge (Solo Administradores)
- `/mcchat <acción> [canal]` - Configura el puente de chat
  - `enable` - Activa el puente de chat
  - `disable` - Desactiva el puente de chat
  - `status` - Muestra el estado actual
  - `set_channel` - Configura el canal de Discord
- `/mcsay <mensaje>` - Envía un mensaje al chat del servidor desde Discord

## 🌉 Funcionalidades del Chat Bridge

### ¿Qué hace el Chat Bridge?
El puente de chat conecta el chat de tu servidor de Minecraft con un canal específico de Discord:

**De Minecraft a Discord:**
- 💬 Mensajes de jugadores
- ✅ Notificaciones cuando alguien se une
- ❌ Notificaciones cuando alguien se va
- 💀 Mensajes de muerte (próximamente)

**De Discord a Minecraft:**
- 💬 Comando `/mcsay` para enviar mensajes al servidor
- 🔧 Comandos administrativos con feedback

### Configuración del Chat Bridge

1. **Obtener ID del canal de Discord:**
   - Activa el "Modo Desarrollador" en Discord
   - Clic derecho en el canal → "Copiar ID"

2. **Encontrar la ruta del archivo de logs:**
   - **Windows:** `C:\ruta\a\tu\servidor\logs\latest.log`
   - **Linux:** `/home/usuario/servidor/logs/latest.log`
   - **Docker:** Monta el volumen de logs

3. **Configurar variables de entorno:**
   ```bash
   MC_CHAT_CHANNEL_ID=tu_id_del_canal
   MC_LOG_PATH=/ruta/completa/al/latest.log
   ```

4. **Activar el puente:**
   ```bash
   /mcchat set_channel #tu-canal-minecraft
   /mcchat enable
   ```

## 🌐 Ventajas de la IP Estática

### ✅ **Beneficios:**
- **Firewall seguro**: Puedes restringir el acceso RCON solo a la IP del bot
- **Conexión estable**: IP fija que no cambia entre deployments
- **Azure compatible**: Fácil configuración de reglas de red
- **Monitoreo**: Logs más claros al saber la IP de origen

### 🔧 **Cómo funciona:**
1. Heroku asigna la IP estática de Fixie Socks a tu app
2. El bot usa esta IP para todas las conexiones RCON
3. Azure reconoce la IP y permite la conexión
4. Conexión segura y estable entre Discord y Minecraft

## 🛡️ Seguridad

### Permisos
- Los comandos de **información** pueden ser usados por cualquier usuario
- Los comandos de **administración** requieren permisos de administrador en Discord
- El **chat bridge** solo puede ser configurado por administradores

### Recomendaciones
1. **Contraseña RCON fuerte**: Usa una contraseña segura y única
2. **Firewall restrictivo**: Solo permite conexiones desde la IP de Fixie Socks
3. **Backup**: Siempre ten backups de tu servidor antes de usar comandos administrativos
4. **Canal dedicado**: Usa un canal específico para el chat de Minecraft
5. **Monitoreo**: Revisa logs regularmente para detectar accesos no autorizados

## 🚀 Instalación de Dependencias

El bot instalará automáticamente estas librerías:

```bash
pip install mcstatus>=11.0.0 mcrcon>=2.3 watchdog>=3.0.0 PySocks>=1.7.1
```

## 🔍 Solución de Problemas

### Error: "RCON no configurado"
- Verifica que `MC_RCON_PASSWORD` esté configurado
- Asegúrate de que RCON esté habilitado en `server.properties`

### Error: "No se pudo conectar al servidor"
- Verifica que la IP y puerto sean correctos
- Asegúrate de que el servidor esté online
- Revisa la configuración del firewall de Azure
- Confirma que la IP de Fixie Socks esté permitida

### Error: "Connection refused"
- El servidor puede estar offline
- El puerto puede estar bloqueado en Azure
- La IP de Fixie Socks no está en la whitelist del firewall
- Verifica las reglas de seguridad de Azure

### Problemas de IP Estática
- Verifica que Fixie Socks esté activo: `heroku addons:info fixie-socks`
- Confirma que `FIXIE_SOCKS_HOST` esté configurado automáticamente
- Usa `/mcconfig` para verificar el estado del proxy
- Revisa los logs de Heroku para errores de conexión

### Chat Bridge no funciona
- Verifica que `MC_LOG_PATH` apunte al archivo correcto
- Asegúrate de que el bot tenga permisos de lectura
- Confirma que `MC_CHAT_CHANNEL_ID` sea correcto
- Usa `/mcchat status` para verificar la configuración

### Mensajes no aparecen en Discord
- Verifica que el puente esté activado (`/mcchat enable`)
- Confirma que el canal esté configurado correctamente
- Revisa que el archivo de logs se esté actualizando

## 📝 Ejemplos de Uso

### Comandos básicos:
```bash
# Ver estado del servidor (con información de IP estática)
/mcstatus

# Listar jugadores
/mcplayers

# Ver configuración completa (incluyendo proxy)
/mcconfig

# Ejecutar comando (solo admins)
/mccommand say ¡Hola desde Discord con IP estática!

# Gestionar whitelist (solo admins)
/mcwhitelist add NombreJugador
/mcwhitelist list

# Expulsar jugador (solo admins)
/mckick JugadorMalo Comportamiento inapropiado
```

### Configuración del Chat Bridge:
```bash
# Configurar canal
/mcchat set_channel #minecraft-chat

# Verificar estado
/mcchat status

# Activar puente
/mcchat enable

# Enviar mensaje al servidor
/mcsay ¡Hola jugadores desde Discord!

# Desactivar puente
/mcchat disable
```

## 🎮 Flujo de Trabajo Típico

1. **Configuración inicial:**
   - Agregar Fixie Socks a Heroku
   - Configurar variables de entorno
   - Habilitar RCON en el servidor
   - Configurar firewall de Azure con IP de Fixie Socks
   - Crear canal dedicado en Discord

2. **Activar funcionalidades:**
   - `/mcchat set_channel #minecraft-chat`
   - `/mcchat enable`

3. **Uso diario:**
   - Los jugadores ven automáticamente el chat en Discord
   - Los admins pueden usar `/mcsay` para comunicarse
   - Monitoreo del servidor con `/mcstatus`
   - Conexión segura y estable a través de IP estática

## ✅ **Lista de Verificación**

### Heroku:
- [ ] Fixie Socks add-on instalado
- [ ] Variables de entorno configuradas
- [ ] Bot desplegado correctamente

### Azure/Servidor:
- [ ] IP de Fixie Socks añadida al firewall
- [ ] Puerto 25575 abierto para la IP de Fixie Socks
- [ ] RCON habilitado en server.properties
- [ ] Servidor reiniciado después de cambios

### Discord:
- [ ] Bot con permisos necesarios
- [ ] Canal de chat creado
- [ ] Comandos funcionando correctamente

## 🎮 ¡Disfruta!

¡Tu bot ahora tiene un puente completo entre Minecraft y Discord con IP estática! Los jugadores pueden ver toda la actividad del servidor en tiempo real, y los administradores tienen control total desde Discord con máxima seguridad. 