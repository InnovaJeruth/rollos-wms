---
name: wms-audit
description: Audita el código de la PWA WMS Rollos (TEXCORP), detecta bugs comunes en flujos offline + IndexedDB + GitHub sync, y ejecuta el plan de pruebas manuales. Triggers - "audita el wms", "revisa el código", "busca bugs", "wms audit", "audita la app", "probemos la app". STRICTLY READ-ONLY por defecto - reporta hallazgos en formato markdown estructurado, NUNCA edita archivos sin que el usuario confirme. La salida es un informe con problemas categorizados por severidad y un plan de pruebas paso-a-paso.
---

# WMS Rollos — Auditoría de código + plan de pruebas

Skill para auditar la PWA WMS Rollos antes de cada release o cuando aparece un bug. Cubre patrones específicos del proyecto: PWA offline-first, IndexedDB con concurrencia, GitHub Contents API como backend, Service Worker, sincronización entre múltiples dispositivos.

## Cuándo invocarme

- Antes de cerrar un release / merge a main.
- Cuando el usuario reporta un bug ambiguo ("se duplicó", "no se actualiza", "se quedó colgado").
- Después de un refactor grande (cambio de estructura de datos, migración de IDs, etc.).
- Antes de un piloto en almacén real.

## Comportamiento

**Por defecto: solo lectura.** Genero un informe en markdown con secciones:
1. Resumen ejecutivo
2. Bugs detectados (con severidad)
3. Plan de pruebas manuales
4. Recomendaciones

Si el usuario dice `--fix` o "arregla", procedo a editar. Si no, solo reporto.

---

## Patrones de bugs específicos del proyecto

### A — IndexedDB & concurrencia

| Patrón | Cómo se ve | Cómo verificar |
|---|---|---|
| **Falta de transacción batched** | Loop `for (item of items) await dbPut(...)` con miles de elementos | Buscar `for.*await.*dbPut` en common.js. Cada `dbPut` abre transacción nueva → lento y susceptible a race conditions intermedias |
| **Race entre auto-pull y push manual** | Dos flujos llaman `dbClear` + `dbPut` casi al mismo tiempo (ej: usuario sube Excel, auto-pull se dispara en background) | Buscar todas las llamadas a `dbClear(STORES.inventario)`. Confirmar si están protegidas por lock |
| **`refreshInventoryStatus` durante carga** | Conteo mostrado durante una carga grande refleja estado intermedio (parcialmente borrado o parcialmente repoblado) | Buscar `dbCount(STORES.inventario)` y verificar si se llama durante operaciones de escritura |
| **`dbClear` no espera a que terminen lecturas pendientes** | Pull/parseExcel puede limpiar el store mientras otro código lee | Difícil de auditar sin trazas. Marcar como riesgo si hay >1 escritor potencial al mismo store |

### B — Semántica de datos / nomenclatura

| Patrón | Cómo se ve | Cómo verificar |
|---|---|---|
| **Mismo campo, dos significados** | `inventario_fecha` se setea con `tsISO(new Date())` en un lugar y con `data.updated_at` (timestamp ajeno) en otro | Grep `inventario_fecha`. Si se asigna en 2+ funciones, sospechar |
| **Texto visible aún con jerga interna** | "bin" en lugar de "estante" en alguna pantalla del operario | Grep `>\s*[Bb]in` en HTML y `flash\(.*[Bb]in` en JS |
| **Mensajes con palabra "GitHub" en flujo operario** | Operario ve referencias técnicas (debería ser transparente) | Grep `GitHub` en archivos cargados por index.html (operario) |

### C — Service Worker / cache

| Patrón | Cómo se ve | Cómo verificar |
|---|---|---|
| **SW viejo intercepta requests de versión nueva** | Usuario sigue viendo errores arreglados; consola muestra responses del SW | `sw.js` debe incrementar `CACHE_VERSION` en cada cambio de assets o lógica |
| **SW intercepta `api.github.com` y envuelve errores** | `503 Service Unavailable` que oculta el error real (401, 403, CORS) | Buscar `api.github.com` en `sw.js`. Debería bypass (`return;`) |
| **Cache de respuestas API persistente** | Operario ve inventario viejo aunque hay versión nueva en GitHub | Verificar que SW no cachee respuestas de `api.github.com` |

### D — Async / promesas

| Patrón | Cómo se ve | Cómo verificar |
|---|---|---|
| **Promesa flotante sin await** | Updates async no terminan cuando el handler regresa | Grep `async function` y verificar que cada llamada esté `await`eada |
| **Handler async sin try/catch** | Errores silenciados, el flash de éxito aparece aunque haya fallado | Cada `addEventListener('click', async () => { ... })` debería tener try/catch o las llamadas internas |
| **Cierre del modal antes de terminar la operación** | Usuario cierra panel; operación queda a medio terminar | Verificar que operaciones críticas terminen antes de navegar |

### E — GitHub API

| Patrón | Cómo se ve | Cómo verificar |
|---|---|---|
| **Header no-CORS-safelist** | `Cache-Control: no-cache` en fetch → CORS preflight rechaza | Cualquier header custom en peticiones a `api.github.com` debe estar en la safelist o GitHub debe permitirlo en `Access-Control-Allow-Headers` |
| **PUT sin SHA en archivo existente** | Error 409 / 422 si el archivo ya existe en el repo | Verificar que toda escritura a archivo existente haga GET primero para obtener `sha` |
| **Token con permisos insuficientes** | 403 al escribir | El test de conexión debe verificar `permissions.push === true`, no solo que el repo exista |
| **Archivos > 1MB en Contents API** | 422 al subir grandes | Confirmar que `pushInventoryToGitHub` usa gzip + verifica tamaño antes de PUT |

### F — Estado del operario

| Patrón | Cómo se ve | Cómo verificar |
|---|---|---|
| **`state.modoActivo` corrupto al retomar sesión** | Operario abre app después de crash, pantalla no coincide con modo | Verificar que `loadBatch()` restaura `state.modoActivo` correctamente |
| **`currentBatch` sobrevive después de finalizar turno** | Próxima sesión arranca con batch del turno anterior | Verificar que `clearSesionActual` también borra el batch |
| **Movimientos duplicados al retomar** | Operario escanea, app crashea, retoma, vuelve a escanear → registro doble | Verificar dedup por `lote` al retomar |
| **Lote con espacios o leading zeros** | `21559` y `021559` se almacenan como dos items | `normLote` debe normalizar agresivamente |

---

## Pasos de auditoría (ejecución)

### Paso 1 — Inventario de archivos

```bash
ls -la *.html *.js *.json *.md 2>/dev/null
```

Identificar archivos principales y su rol.

### Paso 2 — Grep automatizado por categoría

Para cada patrón de bugs (A–F arriba) ejecutar el grep correspondiente y reportar matches con contexto.

```bash
# Concurrencia
grep -nE "for.*await.*dbPut|dbClear\(" common.js index.html admin.html

# Semántica
grep -n "inventario_fecha" common.js index.html admin.html

# Textos visibles operario
grep -nE ">\s*[Bb]in[\s<]|flash\([^)]*[Bb]in" index.html

# SW
grep -n "CACHE_VERSION\|api.github.com" sw.js

# Async sin protección
grep -nE "addEventListener\(['\"](click|change)['\"]," index.html admin.html | head -20
```

### Paso 3 — Análisis estático cruzado

- Listar todos los `getElementById` y confirmar que cada ID existe en el HTML (script en `references/check-ids.sh`).
- Listar todas las funciones definidas vs llamadas (heurística simple, marca falsos positivos esperados).

### Paso 4 — Plan de pruebas manuales

Genero una lista numerada de escenarios a probar manualmente con el navegador, con criterios claros de éxito.

Ver `references/test-plan.md` para el plan completo recomendado.

### Paso 5 — Informe

Estructura del informe:

```markdown
# WMS Audit — <fecha>

## Resumen
- Bugs críticos: N
- Bugs medios: N
- Riesgos menores: N

## Críticos (severidad alta, afecta producción)
1. **<título>** — <archivo:línea>
   - Síntoma: ...
   - Causa raíz: ...
   - Fix propuesto: ...
   - Cómo reproducir: ...

## Medios
...

## Plan de pruebas manuales
1. [ ] <test 1>
   - Pasos: ...
   - Resultado esperado: ...
2. [ ] <test 2>
...

## Recomendaciones (no urgente)
- ...
```

---

## Flags

- `--fix`: después de generar el informe, aplico los fixes críticos.
- `--quick`: solo grep automatizado, sin análisis cruzado ni plan de pruebas.
- `--test-only`: solo plan de pruebas, sin grep.
- `--scope=<archivo>`: limita el audit a un solo archivo.

## Salida

Por defecto: el informe se genera como markdown en la conversación (NO se escribe a archivo a menos que el usuario lo pida explícitamente). Si el usuario dice "guarda el informe", se escribe a `AUDIT-<timestamp>.md` en la raíz del proyecto.

## NO hago

- NUNCA edito archivos sin que el usuario diga `--fix` o "aplica los cambios".
- NUNCA borro datos (IndexedDB, archivos del repo) sin confirmación explícita.
- NUNCA hago commits ni push.
- NUNCA toco el repositorio remoto.
- NUNCA expongo tokens en logs aunque los detecte en el código.

Si encuentro un token en un archivo trackeado, lo señalo como bug crítico (debe estar en `.gitignore` o en IndexedDB, no en código fuente).
