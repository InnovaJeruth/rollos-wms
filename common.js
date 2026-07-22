/* =====================================================================
   WMS Rollos TEXCORP — Funciones compartidas (common.js)
   ---------------------------------------------------------------------
   Exporta window.WMS con todos los helpers que comparten index.html
   (operario) y admin.html. Sin dependencias de DOM.
   ===================================================================== */
(function () {
  'use strict';

  // ============================================================
  // IndexedDB
  // ============================================================
  const DB_NAME = 'wms_rollos';
  const DB_VERSION = 1;
  const STORES = {
    config: 'config',
    inventario: 'inventario',
    sesion: 'sesion',
    pendientes: 'pendientes'
  };

  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains(STORES.config)) {
          db.createObjectStore(STORES.config, { keyPath: 'key' });
        }
        if (!db.objectStoreNames.contains(STORES.inventario)) {
          const s = db.createObjectStore(STORES.inventario, { keyPath: 'lote' });
          s.createIndex('producto', 'producto', { unique: false });
        }
        if (!db.objectStoreNames.contains(STORES.sesion)) {
          db.createObjectStore(STORES.sesion, { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains(STORES.pendientes)) {
          db.createObjectStore(STORES.pendientes, { keyPath: 'id' });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  let _db = null;
  async function db() { if (!_db) _db = await openDB(); return _db; }
  function tx(store, mode) { return db().then((d) => d.transaction(store, mode).objectStore(store)); }

  async function dbGet(store, key) {
    const s = await tx(store, 'readonly');
    return new Promise((res, rej) => {
      const r = s.get(key); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
    });
  }
  async function dbPut(store, value) {
    const s = await tx(store, 'readwrite');
    return new Promise((res, rej) => {
      const r = s.put(value); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
    });
  }
  async function dbDelete(store, key) {
    const s = await tx(store, 'readwrite');
    return new Promise((res, rej) => {
      const r = s.delete(key); r.onsuccess = () => res(); r.onerror = () => rej(r.error);
    });
  }
  async function dbGetAll(store) {
    const s = await tx(store, 'readonly');
    return new Promise((res, rej) => {
      const r = s.getAll(); r.onsuccess = () => res(r.result || []); r.onerror = () => rej(r.error);
    });
  }
  async function dbClear(store) {
    const s = await tx(store, 'readwrite');
    return new Promise((res, rej) => {
      const r = s.clear(); r.onsuccess = () => res(); r.onerror = () => rej(r.error);
    });
  }
  async function dbCount(store) {
    const s = await tx(store, 'readonly');
    return new Promise((res, rej) => {
      const r = s.count(); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
    });
  }

  // Reemplaza COMPLETAMENTE el contenido de un store en una sola transaccion atomica.
  // Mucho mas rapido que clear() + N x put() con await individual, y elimina la
  // ventana donde un lector podria ver el store vacio o a medio poblar.
  async function dbReplaceStore(storeName, items) {
    const database = await db();
    return new Promise((resolve, reject) => {
      const t = database.transaction(storeName, 'readwrite');
      const s = t.objectStore(storeName);
      s.clear();
      let written = 0;
      for (const item of items) {
        if (item) { s.put(item); written++; }
      }
      t.oncomplete = () => resolve(written);
      t.onerror = () => reject(t.error);
      t.onabort = () => reject(t.error || new Error('Transaction aborted'));
    });
  }

  // ============================================================
  // Lock de inventario — serializa parseExcel / pull / push
  // ============================================================
  // Sin esto, dos operaciones que limpian+repueblan el store concurrentemente
  // pueden cruzarse y dejar conteos transitorios incorrectos o duplicados.
  let _invLockPromise = Promise.resolve();
  async function withInventarioLock(label, fn) {
    const prev = _invLockPromise;
    let release;
    _invLockPromise = new Promise((r) => { release = r; });
    try {
      await prev;
      return await fn();
    } finally {
      release();
    }
  }

  // ============================================================
  // Utilidades
  // ============================================================
  function uuidv4() {
    if (crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }
  function pad2(n) { return String(n).padStart(2, '0'); }
  function fechaISO(d) { return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()); }
  function horaISO(d) { return pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds()); }
  function tsISO(d) {
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + 'T' +
           pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  }
  function normBin(s) { return String(s || '').trim().toUpperCase(); }
  function normLote(s) { return String(s || '').trim() || '0'; }
  function shortId() { return Math.random().toString(36).slice(2, 8); }

  // Formatea "YYYY-MM-DD" → "DD/MM/YYYY"
  function fmtFecha(isoDate) {
    if (!isoDate) return '-';
    const m = String(isoDate).match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? `${m[3]}/${m[2]}/${m[1]}` : String(isoDate);
  }
  // Formatea ISO timestamp → "DD/MM/YYYY HH:MM:SS" en UTC-5 (Peru).
  // Si el string termina en Z se asume UTC y se aplica -5h; si no, se usa local.
  function fmtTS(isoTS) {
    if (!isoTS) return '-';
    const s  = String(isoTS);
    const ms = Date.parse(s);
    if (isNaN(ms)) return s;
    const utc = s.endsWith('Z');
    const d   = utc ? new Date(ms - 5 * 3600000) : new Date(ms);
    const dd  = pad2(utc ? d.getUTCDate()    : d.getDate());
    const mo  = pad2(utc ? d.getUTCMonth()+1 : d.getMonth()+1);
    const yy  = utc ? d.getUTCFullYear()     : d.getFullYear();
    const hh  = pad2(utc ? d.getUTCHours()   : d.getHours());
    const mi  = pad2(utc ? d.getUTCMinutes() : d.getMinutes());
    const ss  = pad2(utc ? d.getUTCSeconds() : d.getSeconds());
    return `${dd}/${mo}/${yy} ${hh}:${mi}:${ss}`;
  }

  function b64encodeUtf8(str) { return btoa(unescape(encodeURIComponent(str))); }
  function b64decodeUtf8(b64) {
    const clean = String(b64 || '').replace(/\s/g, '');
    try { return decodeURIComponent(escape(atob(clean))); }
    catch (e) { return atob(clean); }
  }

  // ============================================================
  // gzip (CompressionStream nativo, Chrome 80+)
  // ============================================================
  function hasGzipSupport() {
    return typeof CompressionStream !== 'undefined' && typeof DecompressionStream !== 'undefined';
  }
  async function gzipStringToBytes(str) {
    const stream = new Blob([str]).stream().pipeThrough(new CompressionStream('gzip'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }
  async function gunzipBytesToString(bytes) {
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
    return await new Response(stream).text();
  }
  function bytesToBase64(bytes) {
    let bin = '';
    const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    const chunk = 0x8000;
    for (let i = 0; i < arr.length; i += chunk) {
      bin += String.fromCharCode.apply(null, arr.subarray(i, i + chunk));
    }
    return btoa(bin);
  }
  function base64ToBytes(b64) {
    const bin = atob(String(b64 || '').replace(/\s/g, ''));
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return arr;
  }

  // ============================================================
  // Config: lee desde IndexedDB con fallback a PROJECT_CONFIG global
  // ============================================================
  async function loadConfig() {
    const repo = await dbGet(STORES.config, 'repo');
    const branch = await dbGet(STORES.config, 'branch');
    const token = await dbGet(STORES.config, 'token');
    const defaults = (typeof window !== 'undefined' && window.PROJECT_CONFIG) || {};
    // Decodificar token: XOR+base64 (_token_x + _xk) tiene prioridad sobre base64 simple (_token_enc)
    let defaultToken = defaults.token || '';
    if (!defaultToken && defaults._token_x && defaults._xk) {
      try {
        const bytes = base64ToBytes(defaults._token_x);
        const key = defaults._xk & 0xFF;
        defaultToken = Array.from(bytes).map(b => String.fromCharCode(b ^ key)).join('');
      } catch (e) {}
    }
    if (!defaultToken && defaults._token_enc) {
      try { defaultToken = atob(defaults._token_enc); } catch (e) {}
    }
    return {
      repo: repo ? repo.value : (defaults.repo || ''),
      branch: branch ? branch.value : (defaults.branch || 'main'),
      token: token ? token.value : defaultToken
    };
  }
  async function saveConfig(cfg) {
    await dbPut(STORES.config, { key: 'repo', value: cfg.repo });
    await dbPut(STORES.config, { key: 'branch', value: cfg.branch || 'main' });
    await dbPut(STORES.config, { key: 'token', value: cfg.token });
  }
  async function clearConfig() {
    await dbDelete(STORES.config, 'repo');
    await dbDelete(STORES.config, 'branch');
    await dbDelete(STORES.config, 'token');
  }

  // ============================================================
  // Excel → IndexedDB (depende de XLSX cargado por el HTML)
  // ============================================================
  function normalizeHeader(s) {
    return String(s || '')
      .toLowerCase()
      .normalize('NFD')
      .replace(new RegExp('[\\u0300-\\u036F]', 'g'), '')
      .replace(/[._]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }
  function pickColumn(row, candidates) {
    const keys = Object.keys(row);
    const normKeys = keys.map((k) => ({ orig: k, norm: normalizeHeader(k) }));
    for (const cand of candidates) {
      const cn = normalizeHeader(cand);
      const f = normKeys.find((k) => k.norm === cn);
      if (f) return row[f.orig];
    }
    for (const cand of candidates) {
      const cn = normalizeHeader(cand);
      const f = normKeys.find((k) => k.norm.includes(cn));
      if (f) return row[f.orig];
    }
    return '';
  }
  async function parseExcel(file) {
    if (typeof XLSX === 'undefined') throw new Error('SheetJS no cargado');
    const buf = await file.arrayBuffer();
    const wb = XLSX.read(buf, { type: 'array' });
    const sheet = wb.Sheets[wb.SheetNames[0]];
    const rows = XLSX.utils.sheet_to_json(sheet, { defval: '', raw: false });
    if (!rows.length) throw new Error('Excel vacio');

    return withInventarioLock('parseExcel', async () => {
      // 1) Construir la lista en memoria (deduplicando por lote, ultimo gana)
      const byLote = new Map();
      for (const r of rows) {
        const loteRaw = String(pickColumn(r, ['Lote', 'Lote SAP', 'Batch'])).trim();
        if (!loteRaw) continue;
        const lote = normLote(loteRaw);
        byLote.set(lote, {
          lote: lote,
          producto: String(pickColumn(r, ['Producto', 'Material', 'Codigo material', 'Codigo'])).trim(),
          descripcion: String(pickColumn(r, ['Descripcion de producto', 'Descripcion', 'Descripcion material', 'Material descripcion'])).trim(),
          ubicacion: normBin(pickColumn(r, ['Ubicacion', 'Bin', 'Storage Bin'])),
          cantidad: String(pickColumn(r, ['Ctd.', 'Ctd', 'Cantidad', 'Quantity'])).trim(),
          unidad: String(pickColumn(r, ['Unidad medida bal', 'Unidad', 'UM', 'Unit'])).trim()
        });
      }
      const items = Array.from(byLote.values());

      // 2) Reemplazar el store en una sola transaccion atomica
      const count = await dbReplaceStore(STORES.inventario, items);

      // 3) Metadata
      const now = tsISO(new Date());
      await dbPut(STORES.config, { key: 'inventario_published_at', value: now });
      await dbPut(STORES.config, { key: 'inventario_loaded_at', value: now });
      await dbPut(STORES.config, { key: 'inventario_count', value: count });
      // Compat retro
      await dbPut(STORES.config, { key: 'inventario_fecha', value: now });
      return count;
    });
  }

  // ============================================================
  // GitHub API
  // ============================================================
  async function testGithubConnection(cfg) {
    if (!cfg.repo || !cfg.token) throw new Error('Falta repo o token');
    if (!navigator.onLine) throw new Error('Sin conexion');
    const url = `https://api.github.com/repos/${cfg.repo}`;
    const resp = await fetch(url, {
      headers: { 'Authorization': 'token ' + cfg.token, 'Accept': 'application/vnd.github+json' }
    });
    if (resp.status === 401) throw new Error('Token invalido (401)');
    if (resp.status === 403) throw new Error('Token sin permisos (403)');
    if (resp.status === 404) throw new Error('Repo no encontrado o sin acceso (404)');
    if (!resp.ok) throw new Error('GitHub respondio ' + resp.status);
    const j = await resp.json();
    const canWrite = j.permissions && j.permissions.push;
    if (!canWrite) throw new Error('Token sin escritura. Necesita Contents: Read AND WRITE');
    return { full_name: j.full_name, default_branch: j.default_branch, private: j.private, can_write: true };
  }

  async function getGitHubFile(cfg, path) {
    if (!cfg.repo || !cfg.token) throw new Error('GitHub no configurado');
    const url = `https://api.github.com/repos/${cfg.repo}/contents/${path}?ref=${encodeURIComponent(cfg.branch || 'main')}&_=${Date.now()}`;
    const resp = await fetch(url, {
      headers: { 'Authorization': 'token ' + cfg.token, 'Accept': 'application/vnd.github+json' }
    });
    if (resp.status === 404) return null;
    if (!resp.ok) {
      let detail = '';
      try { const j = await resp.json(); detail = j.message || ''; } catch (e) {}
      throw new Error('GitHub GET ' + resp.status + (detail ? ': ' + detail : ''));
    }
    const j = await resp.json();
    return { sha: j.sha, content: b64decodeUtf8(j.content || '') };
  }

  async function putGitHubFile(cfg, path, contentText, sha, message) {
    if (!cfg.repo || !cfg.token) throw new Error('GitHub no configurado');
    if (!navigator.onLine) throw new Error('Sin conexion');
    const url = `https://api.github.com/repos/${cfg.repo}/contents/${path}`;
    const body = {
      message: message || ('upd: ' + path),
      content: b64encodeUtf8(contentText),
      branch: cfg.branch || 'main'
    };
    if (sha) body.sha = sha;
    const resp = await fetch(url, {
      method: 'PUT',
      headers: {
        'Authorization': 'token ' + cfg.token,
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    });
    if (!resp.ok) {
      let detail = '';
      try { const j = await resp.json(); detail = j.message || ''; } catch (e) {}
      throw new Error('GitHub PUT ' + resp.status + (detail ? ': ' + detail : ''));
    }
    return await resp.json();
  }

  async function deleteGitHubFile(cfg, path, sha, message) {
    if (!cfg.repo || !cfg.token) throw new Error('GitHub no configurado');
    if (!navigator.onLine) throw new Error('Sin conexion');
    if (!sha) throw new Error('Se requiere sha para eliminar archivo');
    const url = `https://api.github.com/repos/${cfg.repo}/contents/${path}`;
    const body = {
      message: message || ('del: ' + path),
      sha,
      branch: cfg.branch || 'main'
    };
    const resp = await fetch(url, {
      method: 'DELETE',
      headers: {
        'Authorization': 'token ' + cfg.token,
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    });
    if (!resp.ok) {
      let detail = '';
      try { const j = await resp.json(); detail = j.message || ''; } catch (e) {}
      throw new Error('GitHub DELETE ' + resp.status + (detail ? ': ' + detail : ''));
    }
    return true;
  }

  async function uploadJSONToFolder(cfg, json, carpeta, prefijo) {
    const safeOp = (json.operario || 'sin_operario').replace(/[^a-zA-Z0-9_-]+/g, '_');
    const filename = `${prefijo}_${safeOp}_${json.id || Date.now()}.json`;
    const path = `${carpeta}/${filename}`;
    return putGitHubFile(cfg, path, JSON.stringify(json, null, 2), null, `${prefijo}: ${filename}`);
  }

  // Lista archivos JSON de una carpeta del repo
  async function listGitHubFolder(cfg, folder) {
    if (!cfg.repo || !cfg.token) throw new Error('GitHub no configurado');
    const url = `https://api.github.com/repos/${cfg.repo}/contents/${folder}?ref=${encodeURIComponent(cfg.branch || 'main')}&_=${Date.now()}`;
    const resp = await fetch(url, {
      headers: { 'Authorization': 'token ' + cfg.token, 'Accept': 'application/vnd.github+json' }
    });
    if (resp.status === 404) return [];
    if (!resp.ok) {
      let detail = '';
      try { const j = await resp.json(); detail = j.message || ''; } catch (e) {}
      throw new Error('GitHub LIST ' + resp.status + (detail ? ': ' + detail : ''));
    }
    const j = await resp.json();
    if (!Array.isArray(j)) return [];
    return j.filter((it) => it.type === 'file' && it.name.endsWith('.json'));
  }

  // Cache local de archivos JSON descargados del repo (por sha)
  // Reduce trafico cuando el dashboard se abre repetidamente.
  async function dbGetCachedFile(path) {
    return dbGet('config', 'cache:' + path);
  }
  async function dbPutCachedFile(path, sha, data) {
    return dbPut('config', { key: 'cache:' + path, sha, data });
  }

  // Carga TODAS las auditorias del repo (carpeta auditoria/).
  // Usa cache por sha: si el archivo no cambió, no se vuelve a descargar.
  // Purga entradas cache:* de archivos que ya no existen en GitHub.
  // onProgress(i, total, filename) opcional para mostrar progreso.
  async function loadAuditoriaHistory(cfg, onProgress) {
    const files = await listGitHubFolder(cfg, 'auditoria');

    // Purgar cache stale: borrar entradas cuyo path ya no está en GitHub
    const currentPaths = new Set(files.map((f) => f.path));
    const allCache = await dbGetAll(STORES.config);
    for (const entry of allCache) {
      if (entry.key && entry.key.startsWith('cache:')) {
        const cachedPath = entry.key.slice('cache:'.length);
        if (!currentPaths.has(cachedPath)) {
          await dbDelete(STORES.config, entry.key);
        }
      }
    }

    const result = [];
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      if (onProgress) try { onProgress(i + 1, files.length, f.name); } catch (e) {}
      try {
        // Intento usar cache si el sha no cambió
        const cached = await dbGetCachedFile(f.path);
        if (cached && cached.sha === f.sha && cached.data) {
          result.push(cached.data);
          continue;
        }
        // Bajar y cachear
        const fc = await getGitHubFile(cfg, f.path);
        if (!fc || !fc.content) continue;
        const data = JSON.parse(fc.content);
        await dbPutCachedFile(f.path, f.sha, data);
        result.push(data);
      } catch (e) {
        // Saltar archivos corruptos
      }
    }
    return result;
  }

  // ============================================================
  // Inventario: push (gzip) y pull
  // ============================================================
  async function unwrapInventory(wrapper) {
    if (!wrapper) throw new Error('Wrapper vacio');
    if (wrapper.compressed === 'gzip' && wrapper.data) {
      if (!hasGzipSupport()) throw new Error('Este navegador no soporta gzip (Chrome 80+).');
      const bytes = base64ToBytes(wrapper.data);
      const text = await gunzipBytesToString(bytes);
      return JSON.parse(text);
    }
    if (Array.isArray(wrapper.items)) return wrapper;
    throw new Error('Formato de inventario invalido');
  }

  async function pushInventoryToGitHub(cfg) {
    const items = await dbGetAll(STORES.inventario);
    if (!items.length) throw new Error('No hay inventario local para publicar');
    const updated_at = tsISO(new Date());
    const innerJson = JSON.stringify({ updated_at, count: items.length, items });

    let content;
    if (hasGzipSupport()) {
      const gz = await gzipStringToBytes(innerJson);
      content = JSON.stringify({
        compressed: 'gzip', updated_at, count: items.length, data: bytesToBase64(gz)
      });
    } else {
      content = innerJson;
    }
    if (content.length > 900000) {
      const kb = Math.round(content.length / 1024);
      throw new Error(`Inventario demasiado grande (${kb} KB). Limite GitHub ~1MB.`);
    }
    let sha = null;
    try {
      const existing = await getGitHubFile(cfg, 'inventario/actual.json');
      if (existing) sha = existing.sha;
    } catch (e) {}
    await putGitHubFile(
      cfg, 'inventario/actual.json', content, sha,
      `inv: actualiza inventario (${items.length} rollos, ${Math.round(content.length / 1024)} KB${hasGzipSupport() ? ' gzip' : ''})`
    );
    await dbPut(STORES.config, { key: 'inventario_global_fecha', value: updated_at });
    return { updated_at, count: items.length, size_kb: Math.round(content.length / 1024) };
  }

  async function pullInventoryFromGitHub(cfg) {
    const file = await getGitHubFile(cfg, 'inventario/actual.json');
    if (!file) throw new Error('No hay inventario publicado en GitHub');
    let wrapper;
    try { wrapper = JSON.parse(file.content); }
    catch (e) { throw new Error('Inventario en GitHub corrupto'); }
    const data = await unwrapInventory(wrapper);
    if (!Array.isArray(data.items)) throw new Error('Formato invalido');

    return withInventarioLock('pull', async () => {
      // Deduplicar por lote
      const byLote = new Map();
      for (const it of data.items) {
        if (it && it.lote) byLote.set(it.lote, it);
      }
      const items = Array.from(byLote.values());

      // Reemplazo atomico
      await dbReplaceStore(STORES.inventario, items);

      const now = tsISO(new Date());
      await dbPut(STORES.config, { key: 'inventario_published_at', value: data.updated_at });
      await dbPut(STORES.config, { key: 'inventario_loaded_at', value: now });
      await dbPut(STORES.config, { key: 'inventario_count', value: items.length });
      await dbPut(STORES.config, { key: 'inventario_global_fecha', value: data.updated_at });
      // Compat retro: inventario_fecha apunta a la fecha publicada
      // (lo que la UI usa para "esta viejo")
      await dbPut(STORES.config, { key: 'inventario_fecha', value: data.updated_at });
      return data;
    });
  }

  async function getGithubInventoryDate(cfg) {
    try {
      const file = await getGitHubFile(cfg, 'inventario/actual.json');
      if (!file) return null;
      const wrapper = JSON.parse(file.content);
      return { updated_at: wrapper.updated_at, count: wrapper.count, _wrapper: wrapper };
    } catch (e) { return null; }
  }

  // ============================================================
  // Movimientos: builders, KPIs
  // ============================================================
  function accionFromModo(modo) {
    if (modo === 'masivo') return 'traslado_masivo';
    if (modo === 'regularizacion') return 'regularizacion';
    return 'traslado_individual';
  }

  function makeMov(modoActivo, partial) {
    const accion = (partial && partial.accion) || accionFromModo(modoActivo);
    return Object.assign({
      lote: '', producto: '', descripcion: '',
      bin_sap: '', bin_real: null, discrepancia: false, bin_destino: null,
      cantidad: '', unidad: '', timestamp: null,
      accion: accion, huerfano: false, batch_id: null
    }, partial || {});
  }

  async function lookupInventario(lote) {
    const n = normLote(lote);
    if (!n || n === '0') return null;
    const r = await dbGet(STORES.inventario, n);
    return r || null;
  }

  async function getRollosEnBin(bin) {
    const target = normBin(bin);
    if (!target) return [];
    const all = await dbGetAll(STORES.inventario);
    return all.filter((it) => normBin(it.ubicacion || '') === target);
  }

  function resumenPorAccion(movs) {
    const r = { traslado_individual: 0, traslado_masivo: 0, regularizacion: 0 };
    for (const m of (movs || [])) {
      const a = m.accion || 'traslado_individual';
      if (r[a] !== undefined) r[a]++;
    }
    return r;
  }

  function movimientosEjecutables(movs) {
    return (movs || []).filter((m) => {
      if (m.huerfano) return false;
      if (!m.bin_sap || !m.bin_destino) return false;
      return true;
    });
  }

  function calcularKPIs(s) {
    const movs = s.movimientos || [];
    const tInicio = Date.parse(s.fecha + 'T' + s.hora_inicio);
    const tFin = s.hora_fin ? Date.parse(s.fecha + 'T' + s.hora_fin) : Date.now();
    const duracionSeg = (isNaN(tInicio) || isNaN(tFin)) ? 0 : Math.max(0, Math.round((tFin - tInicio) / 1000));
    return {
      duracion_seg: duracionSeg,
      duracion_min: Math.round(duracionSeg / 60),
      total_movimientos: movs.length,
      total_discrepancias: movs.filter((m) => m.discrepancia).length,
      total_huerfanos: movs.filter((m) => m.huerfano).length,
      total_ejecutables: movimientosEjecutables(movs).length,
      por_accion: resumenPorAccion(movs),
      seg_por_movimiento: movs.length > 0 ? Math.round(duracionSeg / movs.length) : 0
    };
  }

  function makeEjecutableFromSession(s) {
    const movs = movimientosEjecutables(s.movimientos || []);
    return {
      schema: 'ejecutable_v1',
      id: s.id, operario: s.operario, fecha: s.fecha,
      hora_inicio: s.hora_inicio, hora_fin: s.hora_fin,
      total: movs.length,
      movimientos: movs.map((m) => ({
        accion: m.accion || 'traslado_individual',
        lote: m.lote, producto: m.producto || '',
        bin_origen: m.bin_sap, bin_destino: m.bin_destino,
        cantidad: m.cantidad || '', unidad: m.unidad || '',
        batch_id: m.batch_id || null, timestamp: m.timestamp
      }))
    };
  }

  function makeAuditoriaFromSession(s) {
    const movs = s.movimientos || [];
    return {
      schema: 'auditoria_v1',
      id: s.id, operario: s.operario, fecha: s.fecha,
      hora_inicio: s.hora_inicio, hora_fin: s.hora_fin,
      dispositivo: s.dispositivo,
      kpis: calcularKPIs(s),
      huerfanos: movs.filter((m) => m.huerfano).map((m) => ({
        lote: m.lote, bin_real: m.bin_real, timestamp: m.timestamp, batch_id: m.batch_id
      })),
      discrepancias: movs.filter((m) => m.discrepancia && !m.huerfano).map((m) => ({
        lote: m.lote, bin_sap: m.bin_sap, bin_real: m.bin_real, bin_destino: m.bin_destino,
        accion: m.accion, timestamp: m.timestamp, batch_id: m.batch_id
      })),
      movimientos: movs
    };
  }

  async function uploadSesionToGitHub(cfg, sessionLike) {
    if (!sessionLike || !Array.isArray(sessionLike.movimientos)) {
      throw new Error('Sesion invalida');
    }
    const ejecutable = makeEjecutableFromSession(sessionLike);
    const auditoria = makeAuditoriaFromSession(sessionLike);
    const auditResult = await uploadJSONToFolder(cfg, auditoria, 'auditoria', 'auditoria');
    let pendResult = null;
    if (ejecutable.movimientos.length > 0) {
      pendResult = await uploadJSONToFolder(cfg, ejecutable, 'pendientes', 'movimientos');
    }
    return { auditoria: auditResult, pendientes: pendResult };
  }

  // ============================================================
  // Export
  // ============================================================
  window.WMS = {
    // DB
    STORES, openDB, dbGet, dbPut, dbDelete, dbGetAll, dbClear, dbCount, dbReplaceStore,
    withInventarioLock,
    // Utils
    uuidv4, pad2, fechaISO, horaISO, tsISO, normBin, normLote, shortId, fmtFecha, fmtTS,
    b64encodeUtf8, b64decodeUtf8,
    // gzip
    hasGzipSupport, gzipStringToBytes, gunzipBytesToString, bytesToBase64, base64ToBytes,
    // Config
    loadConfig, saveConfig, clearConfig,
    // Excel
    normalizeHeader, pickColumn, parseExcel,
    // GitHub API
    testGithubConnection, getGitHubFile, putGitHubFile, deleteGitHubFile, uploadJSONToFolder,
    listGitHubFolder, loadAuditoriaHistory,
    // Inventario
    unwrapInventory, pushInventoryToGitHub, pullInventoryFromGitHub, getGithubInventoryDate,
    // Movimientos
    accionFromModo, makeMov, lookupInventario, getRollosEnBin,
    resumenPorAccion, movimientosEjecutables, calcularKPIs,
    makeEjecutableFromSession, makeAuditoriaFromSession, uploadSesionToGitHub
  };
})();
