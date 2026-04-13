# SlicerSegelin Ender 3

Herramienta de escritorio en Python para cargar DXF, ajustar geometría en el plano Y/Z y generar G-Code para un sistema CNC de hilo caliente basado en Ender 3.

## Qué hace

- Importa entidades DXF compatibles y las convierte a segmentos de trabajo.
- Permite rotar, reflejar, trasladar y alinear el perfil.
- Simula el recorrido de corte y estima tiempos.
- Exporta G-Code normal, por placas Y×Z y por cortes manuales.
- Puede exportar DXF modificado.

## Estructura principal

- `appSlicerSegelin/app.py`: aplicación principal Tkinter.
- `modelos-3d/`: modelos CAD y piezas imprimibles.
- `ejemplos-gcode/`: G-Code de ejemplo y pruebas.
- `SlicerSegelinEnder3.spec`: paquete PyInstaller normal.
- `SlicerSegelinEnder3_portable.spec`: paquete PyInstaller portable.

## Requisitos

- Python 3.10 o superior
- Dependencias desde `requirements.txt`

## Ejecutar en local

Instala dependencias y lanza la aplicación desde la raíz del proyecto:

1. `pip install -r requirements.txt`
2. `python appSlicerSegelin/app.py`

## Generar ejecutables

Usa PyInstaller con los archivos `.spec` incluidos en la raíz:

- `SlicerSegelinEnder3.spec`
- `SlicerSegelinEnder3_portable.spec`

## Notas

- Los directorios `build/`, `dist/`, `__pycache__/` y el entorno `.venv/` están excluidos del control de versiones.
- Si abres un DXF grande, la app genera trayectorias y capas en memoria; los archivos de salida se guardan aparte.