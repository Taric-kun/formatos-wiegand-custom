"""Pruebas de la secuencia de carga, respaldo, rollback y verificacion."""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from wiegand_tool import backup, loader, sqlgen  # noqa: E402
from wiegand_tool.presets import w26, w34  # noqa: E402


def test_secuencia_carga_in01():
    url = "http://192.168.3.166:8080/dl/u.sql"
    steps = loader.build_in01_load_sequence(url)
    cmds = loader.commands(steps)
    assert cmds[0] == "shell wget http://192.168.3.166:8080/dl/u.sql -O /mnt/mtdblock/u.sql"
    assert cmds[1] == "shell mv /mnt/mtdblock/u.sql /mnt/mtdblock/data/update.sql"
    assert cmds[2] == "shell chmod 777 /mnt/mtdblock/data/update.sql"
    assert cmds[3] == "shell sync"
    assert cmds[4] == "REBOOT"
    # ningun comando supera el umbral de truncado
    for c in cmds:
        assert len(c) <= loader.MAX_CMD_LEN, (c, len(c))


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

    # Genera el bloque de reescritura con dos formatos de entrada (tipo 1).
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
    res = backup.verify_active_formats(db, {1: "Wiegand26"})
    assert res.ok, res.problemas
    assert res.activos[1] == "Wiegand26"

    # Si esperamos otro activo, debe reportar problema.
    res2 = backup.verify_active_formats(db, {1: "Wiegand34"})
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
