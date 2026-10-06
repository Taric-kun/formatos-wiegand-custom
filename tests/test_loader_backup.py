"""Pruebas de la secuencia de carga, respaldo, rollback y verificacion."""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from wiegand_tool import backup, loader, sqlgen  # noqa: E402
from wiegand_tool.presets import w26, w34  # noqa: E402


def test_secuencia_carga_in01():
    # Secuencia probada: limpiar -> wget (sin -O) -> verificar -> borrar original
    # -> renombrar (en staging) -> chmod -> mover (sin renombrar/reemplazar) -> ...
    url = "http://192.168.2.100:8080/dl/u.sql"
    cmds = loader.commands(loader.build_in01_load_sequence(url))
    assert cmds == [
        "shell rm -f /mnt/mtdblock/u.sql",
        "shell rm -f /mnt/mtdblock/update.sql",
        "shell cd /mnt/mtdblock && wget http://192.168.2.100:8080/dl/u.sql",
        "shell ls -la /mnt/mtdblock/u.sql",
        "shell head -c 16 /mnt/mtdblock/u.sql | od -c",
        "shell rm -f /mnt/mtdblock/data/update.sql",
        "shell mv /mnt/mtdblock/u.sql /mnt/mtdblock/update.sql",
        "shell chmod 777 /mnt/mtdblock/update.sql",
        "shell mv /mnt/mtdblock/update.sql /mnt/mtdblock/data/",
        "shell ls -la /mnt/mtdblock/data/update.sql",
        "shell sync",
        "REBOOT",
    ]
    # el mv final no renombra (nombres iguales) y el destino se borro antes
    assert "-O" not in cmds[2]
    for c in cmds:
        assert len(c) <= loader.MAX_CMD_LEN, (c, len(c))


def test_secuencia_carga_sin_renombrar_si_ya_es_update_sql():
    # Si el archivo ya se llama update.sql, se omite el paso de renombrar.
    url = "http://10.0.0.5:8080/dl/update.sql"
    cmds = loader.commands(loader.build_in01_load_sequence(url, short_name="update.sql"))
    # no debe haber un mv staging->staging (renombre a si mismo)
    assert "shell mv /mnt/mtdblock/update.sql /mnt/mtdblock/update.sql" not in cmds
    assert "shell mv /mnt/mtdblock/update.sql /mnt/mtdblock/data/" in cmds


def test_db_replace_conserva_otras_filas(tmp_path):
    # ZKDB.db con tres formatos (tipos 1/2/3); el metodo DB solo cambia lo nuestro.
    db = str(tmp_path / "ZKDB.db")
    con = sqlite3.connect(db)
    con.execute(
        """CREATE TABLE HID_FORMAT(
            ID INTEGER PRIMARY KEY AUTOINCREMENT, Card_Bit INTEGER, Format_Name TEXT,
            Card_Format TEXT, First_Even TEXT, Second_Even TEXT, First_Odd TEXT,
            Second_Odd TEXT, Format_Type INT, Status INT, SiteCode INT)"""
    )
    # Tipos segun el IN01: 3=entrada, 1=salida, 2=interno.
    con.executemany(
        "INSERT INTO HID_FORMAT(Card_Bit,Format_Name,Format_Type,Status) VALUES(?,?,?,?)",
        [(26, "Wiegand26", 3, 1), (26, "IntWiegand26", 2, 1), (26, "Wiegand26out", 1, 1)],
    )
    con.commit()
    con.close()

    from wiegand_tool import dbedit
    nuevo = w34()  # nuevo formato de entrada (tipo 3), activo
    summary = dbedit.apply_formats(db, [nuevo], modo="upsert")
    assert "Wiegand34" in summary.insertados

    filas = backup.read_hid_format(db)
    # Siguen las 3 originales + la nueva = 4; no se borro nada.
    assert len(filas) == 4
    # El activo de entrada (tipo 3) ahora es el nuevo; salida (1) e interno (2) intactos.
    activos_t3 = [f for f in filas if f["Format_Type"] == 3 and f["Status"] == 1]
    assert len(activos_t3) == 1 and activos_t3[0]["Format_Name"] == "Wiegand34"
    assert any(f["Format_Type"] == 1 and f["Status"] == 1 for f in filas)
    assert any(f["Format_Type"] == 2 and f["Status"] == 1 for f in filas)


def test_comando_demasiado_largo_falla():
    url = "http://192.168.3.166:8080/dl/" + "n" * 80 + ".sql"
    try:
        loader.build_in01_load_sequence(url)
        assert False, "deberia haber fallado por largo"
    except loader.LoadError:
        pass


def test_respaldo_y_rollback():
    bkp = loader.commands(backup.build_backup_sequence())
    assert bkp == ["shell cp /mnt/mtdblock/data/ZKDB.db /mnt/mtdblock/data/ZKDB.bak"]
    rb = loader.commands(backup.build_rollback_sequence())
    assert rb[0] == "shell rm /mnt/mtdblock/data/update.sql"
    assert rb[1] == "shell mv /mnt/mtdblock/data/ZKDB.bak /mnt/mtdblock/data/ZKDB.db"
    assert rb[-1] == "REBOOT"
    for c in bkp + rb:
        assert len(c) <= loader.MAX_CMD_LEN


def test_verificacion_lee_y_compara(tmp_path):
    # Arma una ZKDB.db de prueba con HID_FORMAT y aplica el update.sql generado.
    db = str(tmp_path / "ZKDB.db")
    con = sqlite3.connect(db)
    con.execute(
        """CREATE TABLE HID_FORMAT(
            ID INTEGER PRIMARY KEY AUTOINCREMENT, Card_Bit INTEGER, Format_Name TEXT,
            Card_Format TEXT, First_Even TEXT, Second_Even TEXT, First_Odd TEXT,
            Second_Odd TEXT, Format_Type INT, Status INT, SiteCode INT)"""
    )
    con.commit()

    # Genera el bloque de reescritura con dos formatos de entrada (tipo 3).
    f_activo = w26(site_code=0)          # Wiegand26 queda activo
    f_inactivo = w34()
    f_inactivo.status = 0
    block = sqlgen.build_rewrite_block([f_activo, f_inactivo])

    # Traduce el bloque [CREATE_TABLE]{...} a SQL plano y lo ejecuta (simula el boot).
    inner = block.split("{", 1)[1].rsplit("}", 1)[0]
    con.executescript(inner)
    con.commit()
    con.close()

    filas = backup.read_hid_format(db)
    assert len(filas) == 2
    # En el IN01 entrada = tipo 3.
    res = backup.verify_active_formats(db, {3: "Wiegand26"})
    assert res.ok, res.problemas
    assert res.activos[3] == "Wiegand26"

    # Si esperamos otro activo, debe reportar problema.
    res2 = backup.verify_active_formats(db, {3: "Wiegand34"})
    assert not res2.ok
    assert res2.problemas


if __name__ == "__main__":
    import inspect
    import tempfile
    import traceback
    from pathlib import Path

    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                if "tmp_path" in inspect.signature(fn).parameters:
                    fn(Path(tempfile.mkdtemp()))
                else:
                    fn()
                print(f"PASS {name}")
                passed += 1
            except Exception:
                print(f"FAIL {name}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
