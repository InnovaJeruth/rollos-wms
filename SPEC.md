# WMS Rollos — Especificación Técnica v1.1
**TEXCORP S.A.C. | Proyecto: Automatización de Movimientos de Almacén**
**Fecha:** Junio 2026

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

## 4. Spec PWA v1.1 (M1)

### Stack
- HTML5 + Vanilla JS + CSS (sin frameworks — máxima compatibilidad)
- Service Worker → funcionalidad offline
- IndexedDB → almacenamiento local persistente
- GitHub API (octokit o fetch directo) → sincronización
- Manifest.json → instalable como PWA en Android

### Flujo principal

#### Pantalla 0 — Identificación
- Campo: nombre del operario
- Botón: Iniciar turno
- Registra: hora_inicio

#### Pantalla 1 — Cargar inventario
- Botón: cargar Excel (.xlsx) exportado de /SCWM/MON
- Parseo con SheetJS
- Guardado en IndexedDB
- Muestra: N° registros cargados + fecha de carga
- Si ya hay inventario cargado hoy → saltar directo a Pantalla 2

#### Pantalla 2 — Escanear rollo (flujo principal)
1. Campo activo: **Lote SAP ID** (escaneo QR o código de barras o teclado)
2. Al confirmar → busca en IndexedDB → muestra:
   - Descripción del material
   - "SAP indica bin: **A001-08-08-02**"
   - Pregunta: **¿Está físicamente en esa ubicación?**
   - Botones grandes: ✅ SÍ | ❌ NO
3a. Si SÍ → campo: **Bin destino** (escanear etiqueta estante)
3b. Si NO → campo: **Bin real actual** (escanear donde está físicamente) → luego campo: **Bin destino**
4. Confirmar → agrega a lista → vuelve a paso 1

#### Pantalla 3 — Lista de movimientos
- Lista scrolleable de movimientos pendientes
- Cada ítem muestra: Lote | Origen → Destino | ⚠️ si hay discrepancia
- Botón eliminar por ítem
- Botón: **FINALIZAR TURNO**

#### Pantalla 4 — Finalizar
- Resumen: N° movimientos, N° discrepancias detectadas
- Registra: hora_fin
- Botón: **Sincronizar con GitHub** (requiere señal)
- Estado de sincronización: pendiente / sincronizando / ✅ completado
- Si no hay señal: queda guardado en IndexedDB para sincronizar después

### Estructura JSON de auditoría
```json
{
  "id": "uuid-v4",
  "operario": "Juan Pérez",
  "fecha": "2026-06-03",
  "hora_inicio": "08:12:33",
  "hora_fin": "08:47:10",
  "dispositivo": "navigator.userAgent",
  "total_movimientos": 12,
  "total_discrepancias": 3,
  "movimientos": [
    {
      "lote": "21559",
      "producto": "AP4750",
      "descripcion": "TECAM POLYGOLD AP475",
      "bin_sap": "A001-08-08-02",
      "bin_real": "A001-08-08-02",
      "discrepancia": false,
      "bin_destino": "A003-08-07-03",
      "cantidad": "100",
      "unidad": "M",
      "timestamp": "2026-06-03T08:15:22"
    },
    {
      "lote": "21560",
      "producto": "AP4750",
      "descripcion": "TECAM POLYGOLD AP475",
      "bin_sap": "A001-08-08-02",
      "bin_real": "A002-05-01-01",
      "discrepancia": true,
      "bin_destino": "A003-08-07-03",
      "cantidad": "85",
      "unidad": "M",
      "timestamp": "2026-06-03T08:22:11"
    }
  ]
}
```

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

