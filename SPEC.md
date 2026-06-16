# WMS Rollos — Especificación Técnica v1.2
**TEXCORP S.A.C. | Proyecto: Automatización de Movimientos de Almacén**
**Fecha:** Junio 2026 — v1.2 incorpora 3 modalidades de operación tras reunión de validación

---

## 1. Contexto del Problema

### Situación actual (AS-IS)
- Almacén de telas con ~100 estantes, 3 niveles cada uno, sótano (señal de internet intermitente o nula)
- 5 operarios realizan traslados de rollos entre ubicaciones (bins) diaria o semanalmente
- 30-40 rollos por traslado masivo típico
- Proceso actual: operario mueve rollo físicamente → anota en Excel impreso → encargado digita uno a uno en SAP (/SCWM/ADPROD con movimiento P331)
- Error de digitación ~1%, SAP desactualizado ~50% en ubicaciones
- 2 handhelds Honeywell CK65 (Android, pantalla 4") + celulares personales Android (~6")
- SAP S/4HANA con módulo EWM activo, transacciones clave: /SCWM/ADPROD (P331), /SCWM/MON
- SAP GUI Scripting habilitado en PC de oficina

### Problema raíz
El movimiento físico no se registra en tiempo real en SAP → desincronización entre ubicación física y ubicación lógica en SAP.

---

## 2. Solución Propuesta (TO-BE)

### Arquitectura General
```
HANDHELD/ANDROID (PWA)
├── Funciona OFFLINE (IndexedDB)
├── Escanea QR/código de barras
├── Valida vs inventario SAP cargado
├── Detecta y registra discrepancias
├── Al recuperar señal → sincroniza JSON a GitHub
└── Auditoría completa por operario

        ↓ (GitHub API cuando hay señal)

GITHUB REPO (gratuito, open source)
├── /pendientes/   → JSONs nuevos por procesar
├── /procesados/   → JSONs ya ejecutados
└── /logs/         → registro de ejecuciones

        ↓ (Fase 2 — bot en PC/VM)

PC OFICINA / VM
├── UiPath Community (Fase 2A) → prototipo
├── Python win32com (Fase 2B) → producción
└── Ejecuta /SCWM/ADPROD en SAP GUI
```

### Restricciones técnicas
- Sin servidor dedicado (por ahora)
- Sin internet garantizado en sótano → **offline first obligatorio**
- Todo open source, costo $0
- GitHub Pages como host de la PWA
- IndexedDB como base de datos local en dispositivo
- GitHub como backend/intermediario gratuito

---

## 3. Módulos de desarrollo

| Módulo | Descripción | Fase |
|---|---|---|
| **M1** | PWA — Traslado entre bins con auditoría | **AHORA** |
| **M2** | Bot UiPath → /SCWM/ADPROD | Fase 2A |
| **M3** | Migrar bot a Python win32com | Fase 2B |
| **M4** | Inventario automático desde /SCWM/MON | Con VM |
| **M5** | Entrada de mercancía | Fase 3 |
| **M6** | Despacho a corte | Fase 3 |
| **M7** | Rollos de calidad / reserva | Fase 4 |

---

## 4. Spec PWA v1.2 (M1)

### Stack
- HTML5 + Vanilla JS + CSS (sin frameworks — máxima compatibilidad)
- Service Worker → funcionalidad offline
- IndexedDB → almacenamiento local persistente
- GitHub API (Contents API via fetch) → sincronización
- Manifest.json → instalable como PWA en Android
- BarcodeDetector (Chrome Android) → escaneo de QR/código de barras desde la cámara

### Modos de operación (introducidos en v1.2)

El almacén tiene ~60% de los rollos físicamente fuera de su ubicación SAP. El operario elige al inicio del turno (y puede cambiar mid-turno) entre 3 modos. Una misma sesión puede mezclar los 3.

| Modo | Cuándo usarlo | Output P331 (bot M2) |
|---|---|---|
| **A — Traslado individual** | Movimientos rollo-por-rollo con destinos distintos | P331: `bin_sap → bin_destino` |
| **B — Traslado masivo** | Llevar todo de un bin origen a un bin destino | P331 por rollo: `bin_origen → bin_destino` |
| **C — Regularización** | Recorrer un bin físico y registrar qué hay realmente ahí. Corrige SAP sin mover físicamente. | P331: `bin_sap → bin_real` (bin_real === bin_físico escaneado) |

Rollos huérfanos (físicamente presentes pero SAP no los conoce) se registran con `huerfano: true`. El bot M2 los reporta para acción humana (entrada de mercancía M5).

### Flujo de pantallas

```
screen-identify → screen-mode-select →┬→ screen-scan-lote (Modo A)
                                       │     → screen-confirm-bin → screen-real-bin?
                                       │     → screen-dest-bin → loop
                                       │
                                       ├→ screen-bulk-origin (Modo B)
                                       │     → screen-bulk-list (checkboxes precargados)
                                       │     → screen-bulk-dest → loop
                                       │
                                       └→ screen-reg-bin (Modo C)
                                             → screen-reg-scan (lista en vivo)
                                             → loop al siguiente bin físico

Desde cualquier flujo: botón "Cambiar modo" → screen-mode-select.
Desde mode-select o desde cualquier flujo: "Finalizar turno" → screen-finalize.
```

### Modo A — Traslado individual (igual que v1.1)

1. Escanea lote SAP ID
2. Si lote existe + tiene ubicación SAP → muestra "SAP indica bin: A001-08-08-02. ¿Está aquí? SÍ/NO"
3. Si SÍ → escanea destino → confirma → vuelta al paso 1
4. Si NO → escanea bin real → escanea destino → confirma → vuelta al paso 1
5. Si lote no está en inventario → **bloquear** (P331 no podría ejecutarse)
6. Si lote sin ubicación SAP → salta SI/NO, va directo a bin real (discrepancia automática)

### Modo B — Traslado masivo desde ubicación

1. Escanea bin origen
2. App precarga lista de rollos que SAP dice tener en ese bin (lookup en IndexedDB filtrando `ubicacion === bin_origen`)
3. Muestra lista con checkbox por rollo (todos inicialmente desmarcados)
4. Al escanear cada rollo se marca automáticamente. Si el rollo no estaba en la lista precargada, se agrega como `fuente: 'manual'` (huérfano del bin)
5. Operario puede marcar/desmarcar manualmente con los checkboxes
6. "Continuar" → escanea bin destino → genera N movimientos con `accion: 'traslado_masivo'`, mismo `batch_id`, todos con `bin_destino` común
7. Vuelve al paso 1 (loop para hacer múltiples batches en el turno)
8. **Bloqueado**: origen === destino

### Modo C — Regularización (barrido)

1. Escanea bin físico donde el operario está parado
2. Por cada rollo escaneado:
   - Lookup en inventario
   - Si SAP dice el mismo bin → `accion_calc: 'noop'` (no genera movimiento, solo muestra "✓ En su lugar")
   - Si SAP dice otro bin → `accion_calc: 'mover'` → genera movimiento con `bin_sap = <ubicación SAP>`, `bin_real = bin_destino = <bin físico>`, `discrepancia: true`
   - Si no está en inventario → `accion_calc: 'huerfano'` → genera movimiento con `huerfano: true`, `bin_sap: ''`
3. Operario presiona "Finalizar bin" → batch se commitea a `sesion.movimientos`
4. Vuelve al paso 1 (puede recorrer múltiples bins en el turno)
5. "Cancelar bin" → descarta el batch sin tocar movimientos previamente commiteados

### Estado intermedio (batch en progreso)

`state.currentBatch` se persiste en IndexedDB para recovery de crash. Contiene:

- Modo B: `{modo: 'masivo', bin_origen, batch_id, candidatos: [{lote, ..., marcado, fuente}], bin_destino}`
- Modo C: `{modo: 'regularizacion', bin_fisico, batch_id, escaneados: [{lote, inv, accion_calc}]}`

Al reabrir la app, si hay `sesion` activa + `currentBatch`, ofrece retomar exactamente en la pantalla donde quedó.

### Estructura JSON de auditoría (ampliada v1.2)

```json
{
  "id": "uuid-v4",
  "operario": "Juan Pérez",
  "fecha": "2026-06-03",
  "hora_inicio": "08:12:33",
  "hora_fin": "08:47:10",
  "dispositivo": "navigator.userAgent",
  "total_movimientos": 12,
  "total_discrepancias": 8,
  "resumen_por_accion": {
    "traslado_individual": 2,
    "traslado_masivo": 7,
    "regularizacion": 3
  },
  "movimientos": [
    {
      "accion": "traslado_individual",
      "lote": "21559",
      "producto": "AP4750",
      "descripcion": "TECAM POLYGOLD AP475",
      "bin_sap": "A001-08-08-02",
      "bin_real": "A001-08-08-02",
      "bin_destino": "A003-08-07-03",
      "discrepancia": false,
      "huerfano": false,
      "batch_id": null,
      "cantidad": "100",
      "unidad": "M",
      "timestamp": "2026-06-03T08:15:22"
    },
    {
      "accion": "traslado_masivo",
      "lote": "21601",
      "producto": "AP4750",
      "descripcion": "TECAM POLYGOLD AP475",
      "bin_sap": "A002-04-01-01",
      "bin_real": "A002-04-01-01",
      "bin_destino": "A007-02-01-01",
      "discrepancia": false,
      "huerfano": false,
      "batch_id": "b1a2",
      "cantidad": "85",
      "unidad": "M",
      "timestamp": "2026-06-03T08:42:11"
    },
    {
      "accion": "regularizacion",
      "lote": "22050",
      "producto": "AP4750",
      "descripcion": "TECAM POLYGOLD AP475",
      "bin_sap": "A001-08-08-02",
      "bin_real": "A005-03-02-01",
      "bin_destino": "A005-03-02-01",
      "discrepancia": true,
      "huerfano": false,
      "batch_id": "c5e3",
      "cantidad": "120",
      "unidad": "M",
      "timestamp": "2026-06-03T09:30:00"
    },
    {
      "accion": "regularizacion",
      "lote": "ZZ999",
      "producto": "",
      "descripcion": "",
      "bin_sap": "",
      "bin_real": "A005-03-02-01",
      "bin_destino": "A005-03-02-01",
      "discrepancia": true,
      "huerfano": true,
      "batch_id": "c5e3",
      "cantidad": "",
      "unidad": "",
      "timestamp": "2026-06-03T09:31:42"
    }
  ]
}
```

#### Reglas del bot M2 según `accion`

| accion | huerfano | Acción P331 |
|---|---|---|
| `traslado_individual` | false | P331 `bin_sap → bin_destino` |
| `traslado_masivo` | false | P331 `bin_sap → bin_destino` (o `bin_origen → bin_destino` si bin_sap está vacío y vino como manual) |
| `regularizacion` | false | P331 `bin_sap → bin_real` (regulariza ubicación lógica) |
| `regularizacion` | true | **Skip + log para humano** (necesita entrada de mercancía M5) |

#### Compatibilidad con JSONs antiguos

JSONs guardados antes de v1.2 no tienen `accion`/`huerfano`/`batch_id`/`resumen_por_accion`. El bot debe tratar:
- `accion` ausente → `'traslado_individual'`
- `huerfano` ausente → `false`
- `batch_id` ausente → `null`

### GitHub — estructura del repo
```
rollos-wms/
├── index.html          ← PWA principal
├── manifest.json       ← config PWA instalable
├── sw.js               ← Service Worker offline
├── SPEC.md             ← este archivo
├── pendientes/         ← JSONs por procesar (bot lee aquí)
│   └── .gitkeep
├── procesados/         ← JSONs ejecutados (bot mueve aquí)
│   └── .gitkeep
└── logs/               ← registro ejecuciones bot
    └── .gitkeep
```

### GitHub API — subir JSON
```javascript
// Token con permisos: contents:write
// Guardar en localStorage del dispositivo (configuración inicial)
const GITHUB_TOKEN = 'ghp_...';
const REPO = 'InnovaJeruth/rollos-wms';

async function subirAGithub(jsonData) {
  const filename = `movimientos_${jsonData.operario.replace(' ','_')}_${Date.now()}.json`;
  const content = btoa(JSON.stringify(jsonData, null, 2));
  
  await fetch(`https://api.github.com/repos/${REPO}/contents/pendientes/${filename}`, {
    method: 'PUT',
    headers: {
      'Authorization': `token ${GITHUB_TOKEN}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      message: `mov: ${filename}`,
      content
    })
  });
}
```

---

## 5. UX / UI Guidelines

### Pantallas pequeñas (CK65, 4")
- Botones mínimo **60px de alto**
- Texto mínimo **18px**
- Un solo campo / acción visible a la vez
- Sin scroll en flujo principal de escaneo
- Colores de alto contraste (fondo oscuro, texto claro)
- Feedback visual inmediato al escanear (color + texto grande)

### Pantallas estándar (Android personal, 6"+)
- Puede mostrar más información por pantalla
- Misma PWA — responsive con CSS

### Estados visuales clave
- 🟡 Pendiente de sincronización
- 🟢 Sincronizado con GitHub
- 🔴 Error / discrepancia detectada
- ⚠️ Sin inventario cargado

---

## 6. Datos del sistema

### Formato bins (ubicaciones)
Ejemplo: `A001-08-08-02`
- A001 = tipo de almacén
- 08 = pasillo
- 08 = estante
- 02 = nivel

### Formato Lote SAP ID
- Numérico, ej: `21559`, `0000021594`
- QR contiene solo el número
- Código de barras estándar también disponible en algunos rollos

### Inventario /SCWM/MON (Excel exportado)
Columnas relevantes:
- Ubicación → bin actual en SAP
- Ctd. → cantidad
- Unidad medida bal → unidad (M = metros)
- Producto → código SAP material
- Descripción de producto → nombre
- Lote → Lote SAP ID

---

## 7. Consideraciones de seguridad

- GitHub Token con permisos mínimos (solo contents:write en repo específico)
- Token guardado en IndexedDB del dispositivo (configuración inicial una sola vez)
- Sin datos sensibles de empleados más allá del nombre del operario
- JSONs en GitHub son privados si el repo es privado

---

## 8. Decisiones técnicas tomadas

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| PWA offline-first | App nativa Android | Sin servidor, más simple, mismo resultado |
| GitHub como backend | OneDrive corporativo / carpeta red | Sin permisos IT, gratuito, open source |
| IndexedDB | localStorage | Capacidad mayor, soporta objetos complejos |
| Vanilla JS | React/Vue | Sin build tools, funciona directo en GitHub Pages |
| UiPath primero → Python | Solo Python | Más fácil prototipar flujo SAP GUI visualmente |
| SheetJS para Excel | Pedir CSV | Operarios ya exportan .xlsx de SAP |

