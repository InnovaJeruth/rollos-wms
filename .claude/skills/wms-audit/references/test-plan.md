# Plan de pruebas manuales — WMS Rollos

Plan completo a ejecutar antes de release / piloto. Cada test indica pasos, qué observar y criterio de éxito.

## Pre-requisitos

- Servidor local corriendo: `python -m http.server 8000 --bind 127.0.0.1`
- Chrome con DevTools abierto (F12), pestaña Application + Network visibles
- Token GitHub con `contents: read and write` en el repo
- Excel de inventario de prueba con ≥10 rollos en ≥3 estantes distintos
- Limpieza inicial: F12 → Application → Storage → Clear site data → Ctrl+Shift+R

---

## A — Setup inicial (admin)

### A1. Login admin
1. Abrir `http://localhost:8000/admin.html`
2. Ingresar credenciales (sa/sa)
3. **Esperado**: aparece el menú con secciones (Conexión, Inventario, Sesiones, Dashboard)

### A2. Configuración GitHub — flujo correcto
1. Pegar repo, branch, token
2. Click "Probar conexión" → debe responder `✓ OK`
3. Click "Guardar"
4. Cerrar y reabrir `admin.html`
5. **Esperado**: configuración persiste; entra directo al menú sin pedir credenciales de nuevo (token guardado en IndexedDB)

### A3. Configuración GitHub — token sin write permission
1. Generar un PAT con solo `Contents: Read`
2. Pegar y "Probar conexión"
3. **Esperado**: error claro indicando que falta permiso de escritura, NO debe permitir guardar

---

## B — Inventario

### B1. Carga desde Excel (archivo chico)
1. Subir Excel con 20 rollos
2. **Esperado**:
   - Flash "Inventario cargado: 20 registros"
   - Card de estado muestra "20 rollos"
   - GitHub recibe `inventario/actual.json` (verificar en navegador GitHub)
3. **Bug check**: F12 → Application → IndexedDB → inventario debe tener exactamente 20 entries

### B2. Carga desde Excel (archivo grande)
1. Subir Excel con 20.000+ rollos
2. **Esperado**:
   - Flash de progreso (parseo + push)
   - Tamaño del JSON publicado en GitHub < 1MB (porque va con gzip)
   - Conteo en card coincide con cantidad real
3. **Bug check**: durante la carga, abrir otra pestaña con `admin.html` o `index.html` y observar conteo — NO debe verse el doble de registros temporalmente.

### B3. Bajada desde GitHub
1. Con admin: limpiar inventario local (F12 → IndexedDB → store inventario → clear)
2. Click "Bajar de GitHub"
3. **Esperado**: descarga, descomprime gzip, restaura en local; conteo coincide con GitHub.

### B4. Conflicto entre carga local y pull
1. Cargar Excel A (20 rollos)
2. Inmediatamente click "Bajar de GitHub" (que tiene Excel B con 5 rollos publicado antes)
3. **Esperado**: el estado final es uno de los dos completos (B sobrescribe a A o viceversa según orden). NUNCA debe quedar el merge (25 rollos).

### B5. Reaparición de duplicados (bug reportado)
1. Cargar Excel con 20 rollos
2. Verificar conteo = 20
3. Cargar el MISMO Excel otra vez
4. **Esperado**: conteo = 20 (no 40). Cada `lote` único debe sobrescribir.
5. **Bug check**: en IndexedDB store inventario, verificar que `count(keyPath=lote)` = 20

### B6. Auto-pull al iniciar app del operario
1. Admin: publicar Excel desde admin → confirmar en GitHub
2. Limpiar IndexedDB del operario
3. Abrir `index.html`
4. **Esperado**: auto-pull silencioso; pantalla de identify muestra "X rollos · fecha"
5. **Bug check**: F12 → Network → debe haber 1 GET a `api.github.com/repos/.../inventario/actual.json`, no más.

---

## C — Operario, Modo Individual

### C1. Flujo feliz
1. Como operario: nombre + Iniciar turno
2. Modo Individual
3. Escanear un lote que SAP indica en estante A001-08-08-02
4. Confirmar "Sí" está aquí
5. Escanear destino A003-05-02-01
6. **Esperado**: flash "Movimiento agregado ✓"; vuelve a pantalla de escaneo

### C2. Discrepancia
1. Escanear un lote
2. Cuando pregunta "¿Está aquí?" → "NO"
3. Escanear estante real diferente
4. Escanear destino
5. **Esperado**: en la lista de movimientos aparece marcado como ⚠ Discrep

### C3. Lote no en inventario
1. Escanear un código que no está en el inventario cargado
2. **Esperado**: error claro "Lote no está en inventario SAP", input se limpia, NO permite continuar

### C4. Lote sin ubicación SAP
1. Cargar un Excel con un rollo cuya celda `Ubicación` esté vacía
2. Como operario escanear ese lote
3. **Esperado**: salta directo a "Estante real", no muestra la pregunta SÍ/NO

### C5. Duplicado en sesión
1. Hacer un movimiento del lote 21559
2. Inmediatamente escanear de nuevo el mismo lote 21559
3. **Esperado**: confirm dialog "Este lote ya está en la sesión actual..."

---

## D — Modo Masivo

### D1. Precarga + escaneo
1. Modo Masivo → escanear estante origen que tiene 5 rollos según SAP
2. **Esperado**: aparecen los 5 rollos como checkboxes desmarcados
3. Escanear 3 de ellos → quedan marcados
4. Click "Continuar al estante destino"
5. Escanear destino
6. **Esperado**: 3 movimientos en la lista con `accion: traslado_masivo`, mismo `batch_id`

### D2. Origen = destino bloqueado
1. Modo Masivo → escanear A001-08-08-02 como origen
2. Marcar 1 rollo
3. Escanear A001-08-08-02 como destino
4. **Esperado**: error "Origen y destino son el mismo estante"

### D3. Rollo manual no precargado
1. Modo Masivo → escanear origen
2. Escanear un lote que NO está en la lista precargada
3. **Esperado**: se agrega con tag "Manual" o "Huérfano"

### D4. Cancelar batch
1. Modo Masivo → escanear origen → marcar 3 rollos
2. Click "Cancelar este estante"
3. Confirmar
4. **Esperado**: vuelve a screen origen, los 3 movs NO están en sesión

---

## E — Modo Regularización

### E1. Tres casos en un batch
1. Modo Regularización → escanear estante físico A005-03-02-01
2. Escanear rollo que SAP dice estar en A005-03-02-01 → debe mostrar "✓ En su lugar"
3. Escanear rollo que SAP dice en otro estante → debe mostrar "↻ Regularizar"
4. Escanear rollo desconocido → debe mostrar "⚠ Huérfano"
5. Click "Finalizar este estante"
6. **Esperado**: 2 movimientos en sesión (el "en su lugar" NO genera mov)

### E2. Bin equivocado, cancelar
1. Modo Regularización → escanear estante A
2. Escanear 5 rollos
3. "Cancelar este estante"
4. **Esperado**: batch descartado; movs previos del turno intactos

---

## F — Persistencia y recovery

### F1. Crash recovery — Modo B mid-batch
1. Modo Masivo → escanear origen → marcar 5 rollos
2. Cerrar la pestaña del navegador (no la app entera)
3. Reabrir `index.html`
4. **Esperado**: confirm "Hay batch del modo masivo... ¿retomar?"; al aceptar va a screen-bulk-list con los 5 rollos marcados

### F2. Recuperar sesión sin batch
1. Hacer un turno con 3 movimientos
2. Cerrar pestaña sin terminar turno
3. Reabrir
4. **Esperado**: confirm "Hay sesión en curso con 3 movs ¿retomar?"

### F3. Cambio de modo mid-turno
1. Hacer 1 mov individual
2. Click "Cambiar modo" → seleccionar Masivo → hacer un batch
3. Cambiar a Regularización → hacer otro batch
4. Finalizar turno
5. **Esperado**: JSON de auditoría tiene `resumen_por_accion: {individual: 1, masivo: N, regularizacion: M}`

---

## G — Sincronización GitHub

### G1. Finalizar turno con conexión
1. Hacer 1 turno con 3 movs (uno huérfano)
2. "Guardar y terminar turno"
3. **Esperado**:
   - Sube `auditoria/auditoria_*.json` con TODO incluido (3 movs)
   - Sube `pendientes/movimientos_*.json` con SOLO ejecutables (2 movs, sin huérfano)
   - Flash "Sincronizado correctamente"
   - Volver a pantalla identify

### G2. Finalizar sin conexión
1. F12 → Network → cambiar a "Offline"
2. Hacer 1 turno → finalizar
3. **Esperado**: flash "Guardado. Se subirá cuando haya conexión"
4. Restaurar Network → "Online"
5. **Esperado**: en menos de 10s la sesión queda subida (auto-sync silencioso)

### G3. Token expirado mid-sesión
1. Configurar token válido, hacer movimientos
2. Sin cerrar la app, revocar el token en GitHub
3. Finalizar turno
4. **Esperado**: error claro 401, datos guardados localmente, NO se pierde nada

### G4. Sesión grande (1000 movimientos)
1. Hacer 1000+ movimientos en una sola sesión (simulado con script)
2. Finalizar
3. **Esperado**: archivos < 1MB en GitHub; si excede, error con instrucción al usuario

---

## H — Panel admin

### H1. Secciones del menú
1. Login admin → cada sección debe abrir con click
2. **Esperado**: navegación entre secciones funciona; "← Menú" vuelve al menú principal

### H2. Dashboard global
1. Con al menos 2 sesiones publicadas en GitHub
2. Abrir Dashboard → "Recalcular"
3. **Esperado**:
   - Status muestra progreso "Descargando 1/2..."
   - Cards con KPIs poblados
   - Tabla por operario lista

### H3. Cache del dashboard
1. Dashboard cargado con N archivos
2. Click "Recalcular" otra vez (sin cambios en GitHub)
3. **Esperado**: carga instantánea (todos hits de cache); 0 GETs nuevos a `api.github.com`
4. **Bug check**: F12 → Network → confirmar que no hay descargas nuevas

### H4. Sesiones pendientes
1. Si hay sesiones locales sin subir, deben aparecer en lista
2. Click "Sincronizar pendientes"
3. **Esperado**: cada una sube, se borra del local, cuenta llega a 0

### H5. Descartar sesión en curso
1. Operario deja una sesión a medias
2. Admin → Sesiones → Descartar
3. Confirm dialog
4. **Esperado**: sesión + batch eliminados; operario al reabrir empieza limpio

---

## I — Service Worker

### I1. Actualización tras nueva versión
1. Subir cambio en `index.html` o `common.js`
2. Bump `CACHE_VERSION` en `sw.js`
3. F12 → Application → Service workers → ver versión activa
4. Refresh (Ctrl+R, NO hard refresh)
5. **Esperado**: SW se actualiza solo a la nueva versión

### I2. Offline después de visita previa
1. Cargar la app online una vez (todos los recursos cacheados)
2. F12 → Network → Offline
3. Refresh
4. **Esperado**: app carga igual (HTML + CSS + JS desde cache)

### I3. SW NO intercepta api.github.com
1. F12 → Network
2. Hacer un GET a GitHub desde la app
3. Observar la columna "Initiator" o "Type"
4. **Esperado**: la respuesta NO viene del SW; es directa al server

---

## J — Casos extremos

### J1. Inventario con headers extraños del Excel
1. Excel con columna "Ubicación" (con acento)
2. Cargar
3. **Esperado**: campo `ubicacion` se llena correctamente en cada item (no vacío)

### J2. Lote con caracteres especiales
1. Lote `J123-456-789` o `XYZ_001`
2. Escanear / digitar
3. **Esperado**: se acepta y se almacena tal cual

### J3. Estante con formato no estándar
1. Estante `AREA-PASILLO-NIVEL` (sin números)
2. Escanear como destino
3. **Esperado**: pide confirmación "parece un código no estándar", se acepta si el operario confirma

### J4. Cámara no disponible
1. PC sin cámara
2. **Esperado**: NO aparece el botón 📷 al lado del input

### J5. PWA instalada y luego reset
1. Instalar PWA en Android
2. Desinstalar
3. Reinstalar
4. **Esperado**: IndexedDB se preserva (es independiente de la instalación)

---

## Criterio de éxito global

✅ **Listo para piloto** cuando:
- Todos los tests A–G pasan
- ≥80% de tests H pasan
- 100% de I pasa
- ≥60% de J pasa (los específicos del hardware se prueban en el handheld)

❌ **Bloquear release** si:
- Cualquier test de la sección B falla con duplicación o pérdida de datos
- Cualquier test de la sección F falla con pérdida de movimientos
- Cualquier test de la sección G falla con corrupción del JSON
- Test I3 falla (SW intercepta GitHub API)
