# Herramienta de formatos Wiegand custom (ZKTeco IN01)

Herramienta para **crear y ajustar formatos Wiegand personalizados** y generar
el **archivo de actualización** que los carga en relojes **ZKTeco IN01**
(plataforma ZMM/MIPS). La tabla objetivo en el equipo es `HID_FORMAT`, dentro de
`ZKDB.db`.

> Primera entrega: target **IN01** solamente. Otras plataformas (SenseFace /
> ZAM70) quedan fuera de alcance por ahora.

## Qué hace hoy

- **Motor de formatos** (`wiegand_tool/core.py`): a partir del nº de bits y las
  posiciones de site/card y paridades, genera `Card_Format` y las máscaras
  `First_Even` / `First_Odd` (y `Second_*` si aplica), con validación.
- **Presets** (`wiegand_tool/presets.py`): W26 (confirmado contra una fila real
  del equipo), W34, W37 y HID 35-bit Corporate 1000 (estos tres, editables y
  marcados *a revisar* antes de producción).
- **Generador del archivo de actualización** (`wiegand_tool/sqlgen.py`): formato
  de bloques del equipo `[CREATE_TABLE]{ delete…; insert… }`, **UTF-8 sin BOM,
  LF**, comillas dobles y nombres de columna con guion bajo. Dos modos:
  - *reescribir tabla* (`delete` total + un `insert` por formato), y
  - *solo activar* (cambia `Status` sin borrar ni insertar).

## Pendiente (hoja de ruta)

- Interfaz gráfica para editar y previsualizar formatos.
- Flujo de carga en el IN01 vía ADMS/PUSH (`wget` a `/mnt/mtdblock` → `mv` a
  `data/update.sql` → `chmod` → `sync` → `REBOOT`, con selección por SN).
- Respaldo + rollback antes de cada cambio y verificación post-aplicación.

## Reglas de oro (del trabajo previo sobre la flota)

1. Siempre **respaldar `ZKDB.db`** antes de tocar nada y **verificar** después.
2. El `.sql` siempre **UTF-8 sin BOM, LF** (un BOM rompe la primera sentencia).
3. Comandos shell **cortos** (< ~90 chars): el firmware trunca lo que excede.
4. Nunca `cp` sobre `ZKDB.db` en vivo (está bloqueada) → editar una copia + `mv`.
5. Operar **por SN**, nunca contra "all".

## Pruebas

```bash
python3 tests/test_core.py
```
