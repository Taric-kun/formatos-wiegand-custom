# Herramienta de formatos Wiegand custom (ZKTeco IN01)

Herramienta para **crear y ajustar formatos Wiegand personalizados** y generar
el **archivo de actualización** que los carga en relojes **ZKTeco IN01**
(plataforma ZMM/MIPS). La tabla objetivo en el equipo es `HID_FORMAT`, dentro de
`ZKDB.db`.

> Primera entrega: target **IN01** solamente. Otras plataformas (SenseFace /
> ZAM70) quedan fuera de alcance por ahora.

## Cómo se usa (app web local)

```bash
python3 app.py --port 8080 --myip <IP_LAN_DE_ESTA_PC>
```

Abre `http://<IP_LAN>:8080/` en el navegador. No necesita dependencias externas
(solo Python 3.6+). Apunta el reloj a esta PC:

```
SET OPTIONS WebServerURLModel=0,WebServerPort=8080,ICLOCKSVRURL=<IP_LAN>,IsSupportSSL=0
REBOOT
```

Flujo en la interfaz:
1. **Editor**: parte de un preset, ajusta `Card_Format` y la cobertura de cada
   paridad (click en los bits), y previsualiza máscaras y una trama de ejemplo.
2. **Tabla**: agrega uno o varios formatos y elige *reescribir tabla* o
   *solo activar*. Pulsa **Generar** para construir el `update.sql`.
3. **Cargar en el reloj**: elige el **SN**, deja marcado *Respaldar primero*,
   mira los comandos exactos y pulsa **Cargar**. Hay dos métodos:
   - **update.sql** (secuencia probada en el IN01): `rm` del staging →
     `cd && wget` (sin `-O`) → verificación (`ls`, `head | od -c`) → `mv` a
     `data/update.sql` → `chmod` → `ls` → `sync` → `REBOOT`. Solo a ese SN.
   - **Reemplazar ZKDB.db** (recomendado, conserva todo): trae la `ZKDB.db`
     real, modifica en ella **solo** tu formato (agrega/activa) sin borrar el
     resto, y reemplaza la base con `mv` + `REBOOT`. Evita el riesgo de dejar el
     lector en blanco que tiene el `delete`+`insert` del `update.sql`.
4. **Verificación**: trae una copia de `ZKDB.db` y compara el formato activo.

> Sobre el `wget`: BusyBox guarda el archivo con el nombre del URL, así que el
> archivo generado debe llamarse igual que el que baja (`u.sql` / `z.db`). El
> `rm` previo evita el `File exists` y nunca se usa `wget -O` (dejaba el archivo
> truncado/vacío y el lector quedaba en blanco).

El panel crudo de ZK Commander sigue disponible en `/panel`.

## Componentes

- **Motor de formatos** (`wiegand_tool/core.py`): genera `Card_Format` y las
  máscaras `First_Even`/`First_Odd` (y `Second_*` si aplica), con validación y
  cálculo de la trama para un site/card de ejemplo.
- **Presets** (`wiegand_tool/presets.py`): W26 (confirmado contra una fila real
  del equipo), W34, W37 y HID 35-bit Corporate 1000 (estos tres, editables y
  marcados *a revisar* antes de producción).

> **Format_Type (comportamiento real del IN01):** `3` = entrada/lectura,
> `1` = salida/Wiegand out, `2` = interno/IntWiegand. El firmware los interpreta
> al revés de lo que indicaba la ingeniería inversa inicial (verificado en equipo).
- **Generador del `update.sql`** (`wiegand_tool/sqlgen.py`): bloques
  `[CREATE_TABLE]{ delete…; insert… }`, **UTF-8 sin BOM, LF**, comillas dobles,
  nombres de columna con guion bajo. Modos *reescribir tabla* y *solo activar*.
- **Carga** (`wiegand_tool/loader.py`): secuencia PUSH probada para el IN01
  (`rm`→`cd && wget`→verificación→`mv`→`chmod`→`sync`→`REBOOT`), y la variante de
  reemplazo de `ZKDB.db`, con nombres cortos y control del largo de cada comando
  (< ~90 chars) para evitar el truncado del firmware.
- **Edición de la base** (`wiegand_tool/dbedit.py`): modifica `HID_FORMAT` sobre
  una copia local de `ZKDB.db` (upsert/activar) conservando el resto.
- **Respaldo/rollback/verificación** (`wiegand_tool/backup.py`): respalda
  `ZKDB.db`, deshace un cambio, y lee `HID_FORMAT` desde una copia descargada
  para comparar el formato activo.
- **Servidor PUSH/ADMS** (`zk_panel.py`): base de ZK Commander, reutilizada como
  capa de transporte. **`app.py`** la extiende con el editor y el flujo de carga.

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
