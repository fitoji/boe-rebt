# REBT — Visor offline del Reglamento Electrotécnico de Baja Tensión

Visor estático (solo HTML + JS) que lee los capítulos en Markdown del REBT, genera un índice ordenado con enlaces a cada capítulo y renderiza el contenido con modo light, fuente Nunito y todas las imágenes almacenadas localmente. No depende de conexión a internet ni de CDNs externos.

## Estructura del repositorio

```
boe-rebt/
├── index.html              # Visor estático (abrir en el navegador)
├── README.md               # Este archivo
├── assets/
│   ├── github-markdown.css # Estilos del contenido Markdown (modo light)
│   ├── marked.min.js       # Renderizador Markdown (local)
│   ├── nunito.css          # Fuente Nunito (@font-face, archivos .ttf locales)
│   └── fonts/
│       ├── Nunito-Regular.ttf
│       ├── Nunito-600.ttf
│       └── Nunito-700.ttf
└── rebt_salida/
    ├── md/                 # Capítulos en Markdown (54 archivos)
    │   ├── 00_reglamento.md
    │   ├── ITC-BT-01.md … ITC-BT-52.md
    │   └── zz_informacion-relacionada.md
    └── imgs/               # 63 imágenes del BOE descargadas (offline)
```

## Cómo usarlo

1. Abre `index.html` en cualquier navegador moderno (Chrome, Edge, Firefox, etc.).
2. Haz clic en **📂 Seleccionar carpeta de Markdown** y elige la carpeta `rebt_salida/md/`.
3. Se cargará el índice ordenado:
   - `00 Reglamento`
   - `ITC-BT-01` … `ITC-BT-52`
   - `Información relacionada`
4. Haz clic en cualquier capítulo para leerlo. Incluye:
   - Navegación Anterior / Siguiente
   - Buscador de capítulos
   - Enlaces directos a cada encabezado dentro del capítulo (`#`)
   - URL actualizada con el slug del capítulo (ej. `#ITC-BT-01`)

## Características

| Característica | Detalle |
|----------------|---------|
| **100 % offline** | CSS, JS, fuentes e imágenes están en disco local |
| **Modo light forzado** | Fondo blanco y texto oscuro en todo el documento y el contenido Markdown |
| **Fuente Nunito** | Pesos 400, 600 y 700, cargados desde `assets/fonts/` |
| **Imágenes locales** | Las 63 imágenes del BOE descargadas en `rebt_salida/imgs/`; no se necesitan peticiones externas |
| **Índice automático** | Ordenado: reglamento → ITC-BT-01…52 → información relacionada |
| **Navegación** | Botones Anterior/Siguiente, progreso `x / N`, buscador, anclajes por encabezado |

## Ramas

La rama principal es `main` (renombrada de `master`). Si clonás el repo, usá:

```bash
git checkout main
```

## Notas

- El visor lee los archivos `.md` seleccionados en el navegador; no los sube a ningún servidor. Todo se procesa localmente.
- Las imágenes remotas del BOE (`www.boe.es/...`) se reescriben automáticamente a `rebt_salida/imgs/` al renderizar.
- Para agregar un nuevo capítulo, coloca su `.md` en `rebt_salida/md/` y vuelve a cargar la carpeta en el visor.

## Requisitos

Solo un navegador moderno que soporte `showDirectoryPicker` (Chrome/Edge recomendados) o el selector clásico de archivos (Firefox). No se requiere servidor web ni compilación.