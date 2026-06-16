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

  // Token de GitHub (PAT con Contents: Read and write SOLO en este repo)
  // Dejar vacío para que cada dispositivo lo ingrese manualmente.
  // Llenar con un valor para "config global" automática en todos los dispositivos.
  token: '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',

  // Credenciales del panel admin (cliente-side, solo gate de UX)
  admin_user: 'sa',
  admin_pass: 'sa'
};
