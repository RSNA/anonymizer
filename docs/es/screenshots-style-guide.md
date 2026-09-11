# Guía de estilo de capturas

Para autores que actualizan este manual.

## Reglas de captura

- **Tema:** modo claro
- **Idioma:** capture la UI en inglés (`en_US`) al finalizar el manual en inglés
- **PHI:** solo fixtures de prueba — nunca datos de pacientes reales
- **Almacenamiento:** las capturas viven bajo cada flujo numerado como `shots/macos/*.png` y `shots/windows/*.png`
- **Catálogo:** [`docs/screenshots-manifest.yaml`](../screenshots-manifest.yaml) lista cada elemento UX y captura
- **Escala / resolución:** la captura guarda **puntos lógicos de UI** (Retina 2× → 1 px PNG ≈ 1 pt de app), luego `normalize_for_docs` fuerza cada PNG a **`DOCS_SHOT_MAX_WIDTH`** (960): ventanas anchas se reducen, diálogos estrechos llevan letterbox (sin ampliar la UI). Mismo ancho de archivo ⇒ misma escala MkDocs ⇒ el texto UI más pequeño coincide entre páginas.
- **Sin sombras:** las capturas macOS usan `screencapture -o` (omitir sombra de ventana); el borde suave residual se elimina antes de guardar. No publique capturas con sombras proyectadas.
- **Esquinas:** macOS usa captura por ID de ventana (`screencapture -l`) para que los PNG conserven esquinas redondeadas y alfa; Windows usa PrintWindow / BitBlt

## Carpetas de flujo

```
docs/en/02-install/shots/{macos,windows}/
docs/en/03-ai-features-setup/shots/{macos,windows}/
docs/en/05-create-project/shots/{macos,windows}/
docs/en/06-search/shots/{macos,windows}/
docs/en/07-view/shots/{macos,windows}/
docs/en/08-process/02-remove-burned-in-text/shots/{macos,windows}/
docs/en/08-process/03-harmonize-names/shots/{macos,windows}/
docs/en/08-process/04-blur-faces/shots/{macos,windows}/
docs/en/08-process/05-run-on-many-studies/shots/{macos,windows}/
docs/en/09-send/shots/{macos,windows}/
```

Markdown incrusta la ruta **macOS** (el JS del sitio cambia a Windows para visitantes Windows):

`![…](shots/macos/Welcome.png)`

## Captura automatizada

Las herramientas están en [`src/docs_help/`](../../src/docs_help/) (no en el paquete de la aplicación publicada).

**Responsabilidad del desarrollador:** obtenga el código más reciente, ejecute la captura en **macOS** y de nuevo en **Windows**, luego confirme y suba ambos árboles PNG. No hay captura CI/nube.

Requiere una pantalla de escritorio con permiso de captura (Grabación de pantalla en macOS; acceso al escritorio en Windows); Orthanc en `127.0.0.1:4242` (AE `ORTHANC`) para capturas de Buscar/Consulta. Si las capturas salen en blanco, vuelva a conceder el permiso de captura y reejecute con `--force`.

```bash
uv run python -m docs_help --language en_US
uv run python -m docs_help --language en_US --force
uv run python -m docs_help --language en_US --force --only Welcome
```

- Escribe `docs/<lang>/<chapter>/shots/<os>/` donde `<os>` es `macos` o `windows` (SO anfitrión; `--platform auto`)
- **Reanudar por defecto** (`--skip-existing`); use `--force` o `--force-shot ID` para rehacer
- Las demos de Procesar usan solo fixtures **no sintéticas**:
  - **8.1** Quitar PHI de píxeles → `davidson_cxr` (ocultar) + `us_rgb_single_frame` (fundir + Excluir área bajo mindray)
  - **8.2** Harmonize → `CT_Head_With_Contrast` (Vista de Series → resultados completos → mensaje cerebral → corte medio segmentado) + `davidson_cxr` / `us_rgb_single_frame` (fuentes Playbook planar)
  - **8.3** Desenfoque facial → `CT_Head_With_Contrast` (Gaussian)
  - **8.4** Lote → ambas fixtures seleccionadas en el Conjunto de datos
- Fallo suave en capturas de Procesar intensivas en IA cuando faltan modelos
- Fallo duro en capturas de Buscar que dependen de Orthanc cuando falla C-ECHO
- Si falta un PNG de Windows, el sitio publicado usa la imagen macOS

## Capturas prioritarias (V19)

Bienvenido; Funciones de IA; Ajustes de crear proyecto (+ subdiálogos); Panel de control; Buscar; Vista (Conjunto de datos + edición de descripción de serie/estudio + Proyecciones + Serie + CSV de Búsqueda de Pacientes); Procesar (Quitar PHI de píxeles, Harmonize, Face, lote); Enviar (inicial → selección → enviando → enviado).
