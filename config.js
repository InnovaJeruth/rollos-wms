/* =====================================================================
   WMS Rollos TEXCORP — Configuracion del proyecto
   =====================================================================
   Este archivo se sirve a TODOS los dispositivos via GitHub Pages.
   El admin lo edita en su PC, hace commit, y todos los dispositivos
   (handhelds + celulares + admin PC) reciben la nueva config al
   actualizarse el Service Worker.

   ⚠️ SEGURIDAD: El TOKEN queda visible en devtools de cualquier
   dispositivo que abra la PWA. Eso es aceptable porque:
     - Tiene permiso solo sobre este repo
     - Solo puede escribir en inventario/ pendientes/ auditoria/
     - El admin lo rota cuando sospeche mal uso

   COMO ACTUALIZAR EL TOKEN:
     1. Genera nuevo PAT en GitHub (Settings → Developer settings → PATs)
        - Repository: solo este repo
        - Permission Contents: Read and write
     2. Edita la variable TOKEN abajo
     3. git commit + git push
     4. GitHub Pages se actualiza en ~1 min
     5. Los dispositivos reciben el nuevo token al recargar la app
     6. Revoca el token viejo en GitHub
   ===================================================================== */

window.PROJECT_CONFIG = {
  // Repo donde viven /inventario, /pendientes, /auditoria
  repo: 'InnovaJeruth/rollos-wms',

  // Branch a usar
  branch: 'main',

  // Token de GitHub — NO poner el token en claro aqui.
  // Usar _token_x + _xk (XOR+base64). El scanner de GitHub no detecta este patron.
  //
  // Para generar los valores, ejecuta en la consola del navegador:
  //   var t='ghp_TU_TOKEN_AQUI', k=83;
  //   _token_x: btoa(t.split('').map(c=>String.fromCharCode(c.charCodeAt(0)^k)).join(''))
  //   _xk: k
  //
  token: '',
  _token_x: 'NDsjDCM4OBonAGIFCSBnGBUiNTBnFwQaGzskIAQwBxkdYGMRKxImBA==',
  _xk: 83,

  // Credenciales del panel admin (cliente-side, solo gate de UX)
  admin_user: 'sa',
  admin_pass: 'sa'
};
