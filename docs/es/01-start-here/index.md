# Empezar aquí

## Qué hace este programa

El RSNA DICOM Anonymizer es una aplicación independiente que **elimina información de identidad protegida** de los estudios de imagen médica y guarda una copia segura para investigación en su ordenador.

Puede traer imágenes desde una carpeta o desde un sistema de imagen hospitalario, revisarlas, aplicar opcionalmente herramientas de IA (eliminación de texto quemado, nombres estándar de estudio y serie, face blur) y luego enviar los estudios desidentificados a otro sistema o archivo en la nube.

## Objetivo de privacidad

Los nombres de paciente, IDs y otros identificadores en las «etiquetas» del archivo (tags DICOM) se sustituyen o eliminan. Las fechas se desplazan para que la temporalidad dentro de un paciente sea coherente, pero no sea la fecha de calendario. Las herramientas de IA opcionales también pueden ocultar texto dibujado en la propia imagen y desenfocar rasgos faciales en exámenes de cabeza — porque aún pueden identificar a alguien después de limpiar las etiquetas.

## Para quién es

- Radiólogos e investigadores de imagen que curan conjuntos de datos
- Centros que envían estudios a archivos de investigación

## Dos formas de trabajar


| Modo | Ideal para |
| ------------------------ | ------------------------------------------------------------------------------------------------------------ |
| **Ventana de escritorio (GUI)** | Crear proyectos, revisar imágenes, herramientas de IA, exportación |
| **Sin ventana (headless)** | Laboratorio/servidor: seguir recibiendo imágenes o ejecutar lotes de IA por la noche — véase [Ejecutar sin interfaz](../10-headless/) |


!!! important "Cree el proyecto primero en la ventana"
    El modo headless usa un proyecto que ya creó y configuró. Empiece por [Crear un proyecto](../05-create-project/) y pida a TI que ejecute headless si hace falta.

## Siguientes pasos

1. [Instalación y primer inicio](../02-install/)
2. [Configuración de Funciones de IA](../03-ai-features-setup/) (desde Bienvenido)
3. [Palabras que usamos](../04-words-we-use/)
4. [Crear un proyecto](../05-create-project/)
