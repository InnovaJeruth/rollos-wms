# WMS Rollos — Contexto del proyecto

> Este archivo lo lee Claude Code automáticamente al iniciar conversación.
> Última actualización: 2026-06-16 (refactor anti-zombie completado).

## Qué es este proyecto

PWA offline-first para el almacén de telas de **TEXCORP S.A.C.** Reemplaza el proceso manual donde el operario movía un rollo físicamente, anotaba en papel y un encargado digitaba uno-a-uno en SAP (transacción `/SCWM/ADPROD` con tipo P331). El sistema escanea, registra, sincroniza por GitHub, y un bot (Fase 2) ejecuta en SAP automáticamente.

Lectura más amplia: ver [SPEC.md](SPEC.md) (técnico) y [PROPUESTA.md](PROPUESTA.md) (descripción de alcance sin tiempos).

## Arquitectura

```
config.js     → PROJECT_CONFIG (repo+branch+token por defecto, global)
common.js     → WMS.* — librería compartida (IndexedDB, GitHub API, gzip, builders, KPIs)
index.html    → app operario (PWA instalable) — solo flujo de escaneo
admin.html    → panel admin (PC) — config + carga de inventario + dashboard
sw.js         → Service Worker (offline + cache)
manifest.json → PWA instalable

inventario/   ← admin sube actual.json comprimido con gzip (en GitHub)
pendientes/   ← JSONs ejecutables para el bot M2 (P331)
auditoria/    ← JSONs completos con KPIs (dashboard lee de acá)
```

**Regla de oro:** las helpers compartidas SOLO viven en `common.js`. Si una función está en `index.html` o `admin.html`, debe ser específica a esa pantalla (UI, navegación, state local). NO duplicar lo que ya esté en `WMS.*`.

## Modos de operación del operario

1. **Individual** — rollo por rollo, destinos distintos
2. **Masivo** — escanea estante origen, app precarga lista SAP, marca rollos, escanea destino
3. **Regularización** — escanea estante físico, escanea rollos que ve ahí, app detecta `noop` / `mover` / `huerfano` automáticamente
4. **Tareas asignadas** (pendiente de implementar) — operario recibe lista preasignada

Una sesión puede mezclar los 3 modos. Cada movimiento lleva `accion`, `huerfano`, `batch_id`.

## Estado actual

### Funcionando
- Carga de Excel con compresión gzip (soporta 22k+ rollos en <1MB)
- Lock + transacción atómica en `parseExcel` y `pullInventoryFromGitHub` (sin race conditions)
- Fechas separadas: `inventario_published_at` (cuándo se exportó de SAP) vs `inventario_loaded_at` (cuándo este dispositivo lo bajó)
- 3 modos completos con persistencia de `currentBatch` para crash recovery
- Split JSON al sincronizar: `pendientes/` solo ejecutables (sin huérfanos) + `auditoria/` con todo + KPIs
- Dashboard global desde GitHub con cache por `sha` (no re-descarga lo que no cambió)
- Cámara con `BarcodeDetector` (Chrome Android) + fallback al input
- Service Worker `wms-rollos-v2.2.0`

### Pendiente
- **Modo D — Tareas asignadas**: estructura pensada, falta implementar UI y formato JSON de tareas
- **Configuración global desde un solo dispositivo**: actualmente cada dispositivo necesita guardar GitHub config una vez. Ver opciones en `PROPUESTA.md` sección 7.3
- **Bot UiPath/Python** (Fase 2) para ejecutar P331 desde `pendientes/*.json`
- **Gráficos visuales en dashboard** (ahora solo tablas/cards)
- **Filtros por operario/fecha** en el dashboard
- **Exportar dashboard a CSV/Excel**

## Convenciones

- **Vocabulario**: en UI del operario decir "estante", no "bin" (interno). Los campos JSON sí se llaman `bin_sap` / `bin_real` / `bin_destino` (contrato con el bot, no romper).
- **Token GitHub**: NUNCA en código fuente. Vive en IndexedDB (admin lo guarda) o en `config.js` (PROJECT_CONFIG, defaults para piloto). Si lo veo en código fuente debo eliminarlo y avisar.
- **SW version**: bump `CACHE_VERSION` en `sw.js` cada vez que cambie comportamiento de cliente.
- **El operario no ve "GitHub"**: nada técnico en su UI. Solo "Sincronizado" / "Pendiente".
- **Admin behind login** `sa`/`sa` (hardcoded, gate de UX no seguridad real).
- **No hooks, no frameworks, no build tools** — vanilla JS, HTML, CSS.

## Cómo levantar el entorno

```powershell
cd C:\Users\crodriguezt\Documents\JERUTH\TEXCORP\ALMACEN\rollos-wms
python -m http.server 8000 --bind 127.0.0.1
```

Browser: `http://localhost:8000/` (operario) o `http://localhost:8000/admin.html` (admin, login `sa`/`sa`).

Si hay cache stuck: F12 → Application → Storage → **Clear site data** → Ctrl+Shift+R.

## Skill disponible

**`wms-audit`** (en `.claude/skills/wms-audit/`) — audita bugs específicos de este proyecto (IndexedDB races, semántica de datos, SW cache, async, GitHub API, estado operario). Read-only por defecto. Invocar con: "audita el wms" o "revisa el código".

Plan de pruebas manuales completo en `.claude/skills/wms-audit/references/test-plan.md` (10 categorías, 50+ tests).

## Deuda técnica conocida

1. **Token expuesto en historial git**: si el token `github_pat_11B3LSA3Y0...` que estuvo hardcoded en línea 949 de `index.html` se commiteó al repo, REVOCARLO en GitHub Settings → Developer settings.
2. **No hay tests automatizados** — el plan en `wms-audit` es manual. Si se justifica, sumar Playwright.
3. **`refreshOperatorInventoryInfo`** depende del nombre exacto de los IDs del card en pantalla identify; ningún test detecta si los IDs cambian.
4. **El admin podría arrancar más rápido** moviendo el dashboard al final del menú (carga 50+ archivos del repo al abrir).
5. **Cache del dashboard nunca expira por antigüedad** — solo por cambio de sha. Si el admin borra y re-publica con mismo sha (raro), el cache queda stale.

## Decisiones recientes (no obvias del código)

- Modo Masivo: **precarga la lista** del bin origen (no estricto-solo-escaneo). Decisión del usuario tras propuesta de 3 opciones.
- Modo Regularización: **permite huérfanos** marcándolos `huerfano: true`. Decisión del usuario.
- **Filtro por nicho (piloto)** — pospuesto. Primero validar las modalidades, después agregar.
- **Dashboard solo en PC**: en móvil se ve resumen pero el aviso dice "optimizado para PC".

## Archivos importantes (no perder de vista)

| Archivo | Para qué |
|---|---|
| `SPEC.md` | Especificación técnica v1.2 (módulos, schema JSON, decisiones) |
| `PROPUESTA.md` / `PROPUESTA.docx` | Propuesta comercial sin tiempos |
| `.claude/skills/wms-audit/SKILL.md` | Skill de auditoría |
| `.claude/skills/wms-audit/references/test-plan.md` | Plan de pruebas manuales |
| `.claude/plans/tuve-una-nueva-reunion-federated-ullman.md` | Plan del refactor de los 3 modos |
| `generate_propuesta.js` | Script que convierte PROPUESTA.md → DOCX |

## Cómo retomar trabajo en otro chat

1. Claude leerá este archivo automáticamente.
2. Si vas a tocar la app: empieza por hacer `Skill wms-audit` para detectar regresiones.
3. Si vas a tocar el formato de los JSON o agregar Modo D (tareas asignadas), actualizar `SPEC.md` y bump `CACHE_VERSION` en `sw.js`.
4. Cualquier cambio que afecte al operario requiere clear site data + hard refresh para verificarlo.

## Contacto / Cliente

- Cliente: TEXCORP S.A.C. (Perú)
- Almacén: ~100 estantes × 3 niveles, sótano sin internet garantizado
- Operarios: 5 (handheld Honeywell CK65 + celulares personales Android)
- SAP S/4HANA con módulo EWM, transacción objetivo `/SCWM/ADPROD` (P331)
