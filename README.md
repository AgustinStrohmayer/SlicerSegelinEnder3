# SlicerSegelin Ender 3

Aplicación de escritorio en Python para preparar geometría en el plano Y/Z y generar G-Code para un CNC de hilo caliente basado en Ender 3.

## Resumen

- Importa DXF y otras entidades compatibles con `ezdxf`.
- Permite rotar, reflejar, trasladar y alinear perfiles.
- Simula el corte y estima tiempos.
- Exporta G-Code normal, por placas Y×Z y por cortes manuales.
- Exporta el DXF modificado cuando necesitas volver a usar la geometría procesada.

## Estructura del proyecto

- `appSlicerSegelin/app.py` — interfaz y lógica principal de la app.
- `modelos-3d/` — modelos CAD y piezas imprimibles.
- `ejemplos-gcode/` — G-Code de ejemplo y pruebas.
- `archive/` — históricos y variantes antiguas conservadas como referencia.
- `SlicerSegelinEnder3.spec` — build normal con PyInstaller.
- `SlicerSegelinEnder3_portable.spec` — build portable con PyInstaller.

## Requisitos

- Python 3.10 o superior
- Dependencias listadas en `requirements.txt`

## Puesta en marcha

Desde la raíz del repositorio:

1. Instalar dependencias:
	`pip install -r requirements.txt`
2. Ejecutar la app:
	`python appSlicerSegelin/app.py`

## Generación de ejecutables

Los archivos `.spec` de la raíz están preparados para PyInstaller y usan rutas relativas, así que funcionan bien tras clonar el proyecto.

## Cómo colaborar

1. Crea una rama para tu cambio.
2. Mantén el código en `appSlicerSegelin/`.
3. No subas artefactos de `build/`, `dist/` ni `__pycache__/`.
4. Si agregas modelos o ejemplos, colócalos en `modelos-3d/` o `ejemplos-gcode/`.

## Licencia

Este proyecto se publica con licencia MIT. Consulta `LICENSE`.

## Seguridad

Si encuentras un problema de seguridad o un comportamiento inesperado en archivos DXF/G-Code, revísalo primero en un entorno aislado y luego abre un reporte.