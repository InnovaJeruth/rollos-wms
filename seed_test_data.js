/**
 * seed_test_data.js — Sube sesiones de prueba a GitHub para poblar el dashboard.
 * Uso: node seed_test_data.js <GITHUB_TOKEN>
 * Ejemplo: node seed_test_data.js ghp_xxxx
 */

const https = require('https');

const TOKEN = process.argv[2];
const REPO  = 'InnovaJeruth/rollos-wms';
const BRANCH = 'main';

if (!TOKEN) {
  console.error('Uso: node seed_test_data.js <GITHUB_TOKEN>');
  process.exit(1);
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function uuidv4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
}
function pad2(n) { return String(n).padStart(2, '0'); }
function fechaISO(d) { return `${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())}`; }
function horaISO(d)  { return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`; }
function daysAgo(n)  { const d = new Date(); d.setDate(d.getDate() - n); return d; }

function githubPut(path, content, msg) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ message: msg, content: Buffer.from(content).toString('base64'), branch: BRANCH });
    const req = https.request({
      hostname: 'api.github.com',
      path: `/repos/${REPO}/contents/${path}`,
      method: 'PUT',
      headers: {
        'Authorization': `token ${TOKEN}`,
        'Content-Type': 'application/json',
        'User-Agent': 'wms-seed',
        'Content-Length': Buffer.byteLength(body)
      }
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        if (res.statusCode === 200 || res.statusCode === 201) resolve(JSON.parse(data));
        else reject(new Error(`HTTP ${res.statusCode}: ${data}`));
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// ── Generador de sesiones mock ────────────────────────────────────────────────
function makeSession(operario, daysBack, modoMix) {
  const fecha = daysAgo(daysBack);
  const inicio = new Date(fecha);
  inicio.setHours(8 + Math.floor(Math.random() * 3));
  const fin = new Date(inicio.getTime() + (30 + Math.random() * 60) * 60000);

  const movimientos = [];
  const acciones = modoMix || ['traslado_individual', 'traslado_masivo', 'regularizacion'];

  const bins = ['A001-08-08-01','A001-08-08-02','A002-04-01-01','A003-08-07-03',
                'A004-02-03-01','A005-03-02-01','A006-01-01-01','A007-02-01-01'];
  const productos = [
    { codigo: 'AP4750', desc: 'TECAM POLYGOLD AP475' },
    { codigo: 'TC1200', desc: 'TELA CRUDA 120CM' },
    { codigo: 'PL3300', desc: 'POLYESTER LISO 330' },
    { codigo: 'AL0500', desc: 'ALPACA LISA 050' }
  ];

  const totalMovs = 5 + Math.floor(Math.random() * 15);
  const batchId = 'b' + Math.random().toString(36).slice(2,6);

  for (let i = 0; i < totalMovs; i++) {
    const accion = acciones[Math.floor(Math.random() * acciones.length)];
    const prod = productos[Math.floor(Math.random() * productos.length)];
    const binSap = bins[Math.floor(Math.random() * bins.length)];
    const binDest = bins[Math.floor(Math.random() * bins.length)];
    const discrepancia = Math.random() < 0.3;
    const huerfano = accion === 'regularizacion' && Math.random() < 0.1;

    const ts = new Date(inicio.getTime() + (i / totalMovs) * (fin - inicio));
    movimientos.push({
      accion,
      lote: String(20000 + Math.floor(Math.random() * 5000)),
      producto: huerfano ? '' : prod.codigo,
      descripcion: huerfano ? '' : prod.desc,
      bin_sap: huerfano ? '' : binSap,
      bin_real: discrepancia ? bins[Math.floor(Math.random() * bins.length)] : binSap,
      bin_destino: accion === 'regularizacion' ? binSap : binDest,
      discrepancia: discrepancia && !huerfano,
      huerfano,
      batch_id: accion !== 'traslado_individual' ? batchId : null,
      cantidad: String(50 + Math.floor(Math.random() * 200)),
      unidad: 'M',
      timestamp: ts.toISOString()
    });
  }

  const por_accion = { traslado_individual: 0, traslado_masivo: 0, regularizacion: 0 };
  movimientos.forEach(m => { por_accion[m.accion] = (por_accion[m.accion] || 0) + 1; });
  const ejecutables = movimientos.filter(m => !m.huerfano);
  const huerfanos  = movimientos.filter(m => m.huerfano);
  const discrepancias = movimientos.filter(m => m.discrepancia);
  const durSeg = Math.round((fin - inicio) / 1000);

  return {
    id: uuidv4(),
    operario,
    fecha: fechaISO(fecha),
    hora_inicio: horaISO(inicio),
    hora_fin: horaISO(fin),
    dispositivo: 'Honeywell CK65 / Android 11',
    total_movimientos: movimientos.length,
    total_discrepancias: discrepancias.length,
    resumen_por_accion: por_accion,
    movimientos,
    kpis: {
      total_movimientos: movimientos.length,
      total_ejecutables: ejecutables.length,
      total_huerfanos: huerfanos.length,
      total_discrepancias: discrepancias.length,
      duracion_seg: durSeg,
      por_accion
    }
  };
}

// ── Sesiones de prueba ────────────────────────────────────────────────────────
const sesiones = [
  makeSession('Juan Perez',    0, ['traslado_individual', 'traslado_masivo']),
  makeSession('Maria Lopez',   1, ['regularizacion', 'traslado_individual']),
  makeSession('Carlos Quispe', 2, ['traslado_masivo']),
  makeSession('Juan Perez',    3, ['traslado_individual', 'regularizacion']),
  makeSession('Ana Torres',    4, ['traslado_masivo', 'regularizacion']),
  makeSession('Carlos Quispe', 5, ['traslado_individual']),
];

// ── Upload ────────────────────────────────────────────────────────────────────
(async () => {
  console.log(`Subiendo ${sesiones.length} sesiones de prueba a auditoria/...\n`);
  for (const s of sesiones) {
    const filename = `auditoria/auditoria_${s.operario.replace(/\s/g,'_')}_${s.id}.json`;
    try {
      await githubPut(filename, JSON.stringify(s, null, 2), `test: sesion prueba ${s.operario} ${s.fecha}`);
      console.log(`✓ ${filename}`);
    } catch (e) {
      console.error(`✗ ${filename}: ${e.message}`);
    }
  }
  console.log('\nListo. Abre el dashboard en admin.html para verlos.');
})();
