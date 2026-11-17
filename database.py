"""Capa de datos y reglas de negocio del Sistema de Inventario Mayorista (versión 3).

Cadena de venta:  MAYORISTA (vendedor) ──► TENDERO ──► COMPRADOR
  · El tendero compra al mayorista y tiene su propio inventario (con lotes y vencimientos).
  · El comprador SOLO compra a un tendero, nunca al mayorista.
  · Vendedor y tendero tienen ganancias; ambos pueden perder por productos vencidos.

Esta capa NO usa Tkinter: toda la lógica vive aquí para poder probarla de forma automática.
"""
import csv
import glob
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "inventario_mayorista.db")
SCHEMA_VERSION = 3

ROLES = ("Administrador", "Vendedor", "Tendero", "Comprador")
ROLES_MAYORISTA = ("Administrador", "Vendedor")

ESTADOS_ACTIVOS = ("PENDIENTE", "APROBADO", "DESPACHADO")
ESTADOS_FINALES = ("ENTREGADO", "RECHAZADO", "CANCELADO")
ESTADOS_VENTA = ("APROBADO", "DESPACHADO", "ENTREGADO")   # el stock ya salió: cuenta como venta
TRANSICIONES = {
    "PENDIENTE": {"APROBADO", "RECHAZADO", "CANCELADO"},
    "APROBADO": {"DESPACHADO"},
    "DESPACHADO": {"ENTREGADO"},
}
ACCIONES_VENDEDOR = {"APROBADO", "RECHAZADO", "DESPACHADO"}


class ErrorNegocio(Exception):
    """Error esperado (dato inválido, regla incumplida) con mensaje para el usuario."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT UNIQUE NOT NULL COLLATE NOCASE,
    clave TEXT NOT NULL,
    rol TEXT NOT NULL,
    nombre_tienda TEXT NOT NULL,
    direccion TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS productos (          -- inventario del MAYORISTA
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL COLLATE NOCASE,
    lote TEXT NOT NULL COLLATE NOCASE,
    cantidad INTEGER NOT NULL CHECK (cantidad >= 0),
    stock_minimo INTEGER NOT NULL DEFAULT 10,
    precio_costo REAL NOT NULL DEFAULT 0,        -- lo que le cuesta al mayorista (proveedor)
    precio_mayorista REAL NOT NULL,              -- lo que paga el tendero
    precio_sugerido REAL NOT NULL,               -- sugerido para vender al público
    fecha_vencimiento TEXT NOT NULL,
    UNIQUE (nombre, lote)
);
CREATE TABLE IF NOT EXISTS pedidos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL DEFAULT 'MAYORISTA',      -- MAYORISTA: tendero→mayorista | TIENDA: comprador→tendero
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),   -- quien compra
    usuario TEXT NOT NULL,
    tienda TEXT NOT NULL,
    direccion TEXT NOT NULL,
    vendedor_id INTEGER REFERENCES usuarios(id), -- NULL cuando vende el mayorista
    vendedor TEXT NOT NULL DEFAULT 'Mayorista',
    estado TEXT NOT NULL,
    total REAL NOT NULL,
    fecha_creacion TEXT NOT NULL,
    nota TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pedido_items (       -- guarda una "foto" del producto: el historial no depende del inventario
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id INTEGER NOT NULL REFERENCES pedidos(id),
    producto_id INTEGER NOT NULL,                -- id en productos (MAYORISTA) o en inventario_tienda (TIENDA)
    nombre_producto TEXT NOT NULL,
    lote TEXT NOT NULL,
    fecha_vencimiento TEXT NOT NULL,
    cantidad INTEGER NOT NULL,
    costo_unitario REAL NOT NULL DEFAULT 0,      -- lo que le costó al vendedor
    precio_unitario REAL NOT NULL,               -- lo que paga el comprador
    precio_publico REAL NOT NULL                 -- a cuánto lo venderá el tendero
);
CREATE TABLE IF NOT EXISTS historial_pedidos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id INTEGER NOT NULL REFERENCES pedidos(id),
    estado TEXT NOT NULL,
    fecha TEXT NOT NULL,
    usuario TEXT NOT NULL,
    detalle TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS inventario_tienda (  -- inventario de cada TENDERO, por lote
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    nombre_producto TEXT NOT NULL COLLATE NOCASE,
    lote TEXT NOT NULL COLLATE NOCASE,
    fecha_vencimiento TEXT NOT NULL,
    cantidad INTEGER NOT NULL CHECK (cantidad >= 0),
    costo_unitario REAL NOT NULL,                -- lo que pagó al mayorista (promedio ponderado)
    precio_venta REAL NOT NULL,                  -- a cuánto vende al público
    UNIQUE (usuario_id, nombre_producto, lote)
);
CREATE TABLE IF NOT EXISTS movimientos (        -- entradas y salidas del inventario del mayorista
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    producto_id INTEGER,
    producto TEXT NOT NULL,
    lote TEXT NOT NULL,
    tipo TEXT NOT NULL,
    cantidad INTEGER NOT NULL,
    detalle TEXT NOT NULL DEFAULT '',
    usuario TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mermas (             -- pérdidas por productos vencidos
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    usuario_id INTEGER,                          -- NULL = mayorista
    propietario TEXT NOT NULL,
    producto TEXT NOT NULL,
    lote TEXT NOT NULL,
    cantidad INTEGER NOT NULL,
    costo_unitario REAL NOT NULL,
    motivo TEXT NOT NULL,
    usuario TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
-- ---- Validación de datos: la base se defiende sola de lo que se escriba a mano (DBeaver, DB Browser...) ----
-- Fechas como AAAA-MM-DD, cantidades enteras y precios numéricos. Si algo no cumple, la edición se rechaza.
CREATE TRIGGER IF NOT EXISTS validar_productos_ins AFTER INSERT ON productos
WHEN date(NEW.fecha_vencimiento) IS NOT NEW.fecha_vencimiento OR typeof(NEW.cantidad) <> 'integer'
  OR typeof(NEW.stock_minimo) <> 'integer' OR typeof(NEW.precio_costo) NOT IN ('integer', 'real')
  OR typeof(NEW.precio_mayorista) NOT IN ('integer', 'real') OR typeof(NEW.precio_sugerido) NOT IN ('integer', 'real')
BEGIN SELECT RAISE(ABORT, 'Dato invalido en productos: la fecha debe ser AAAA-MM-DD y cantidades/precios solo numeros'); END;
CREATE TRIGGER IF NOT EXISTS validar_productos_upd AFTER UPDATE ON productos
WHEN date(NEW.fecha_vencimiento) IS NOT NEW.fecha_vencimiento OR typeof(NEW.cantidad) <> 'integer'
  OR typeof(NEW.stock_minimo) <> 'integer' OR typeof(NEW.precio_costo) NOT IN ('integer', 'real')
  OR typeof(NEW.precio_mayorista) NOT IN ('integer', 'real') OR typeof(NEW.precio_sugerido) NOT IN ('integer', 'real')
BEGIN SELECT RAISE(ABORT, 'Dato invalido en productos: la fecha debe ser AAAA-MM-DD y cantidades/precios solo numeros'); END;
CREATE TRIGGER IF NOT EXISTS validar_inventario_tienda_ins AFTER INSERT ON inventario_tienda
WHEN date(NEW.fecha_vencimiento) IS NOT NEW.fecha_vencimiento OR typeof(NEW.cantidad) <> 'integer'
  OR typeof(NEW.costo_unitario) NOT IN ('integer', 'real') OR typeof(NEW.precio_venta) NOT IN ('integer', 'real')
BEGIN SELECT RAISE(ABORT, 'Dato invalido en inventario_tienda: la fecha debe ser AAAA-MM-DD y cantidades/precios solo numeros'); END;
CREATE TRIGGER IF NOT EXISTS validar_inventario_tienda_upd AFTER UPDATE ON inventario_tienda
WHEN date(NEW.fecha_vencimiento) IS NOT NEW.fecha_vencimiento OR typeof(NEW.cantidad) <> 'integer'
  OR typeof(NEW.costo_unitario) NOT IN ('integer', 'real') OR typeof(NEW.precio_venta) NOT IN ('integer', 'real')
BEGIN SELECT RAISE(ABORT, 'Dato invalido en inventario_tienda: la fecha debe ser AAAA-MM-DD y cantidades/precios solo numeros'); END;
CREATE TRIGGER IF NOT EXISTS validar_usuarios_ins AFTER INSERT ON usuarios
WHEN NEW.rol NOT IN ('Administrador', 'Vendedor', 'Tendero', 'Comprador') OR NEW.activo NOT IN (0, 1)
BEGIN SELECT RAISE(ABORT, 'Dato invalido en usuarios: rol = Administrador, Vendedor, Tendero o Comprador; activo = 0 o 1'); END;
CREATE TRIGGER IF NOT EXISTS validar_usuarios_upd AFTER UPDATE ON usuarios
WHEN NEW.rol NOT IN ('Administrador', 'Vendedor', 'Tendero', 'Comprador') OR NEW.activo NOT IN (0, 1)
BEGIN SELECT RAISE(ABORT, 'Dato invalido en usuarios: rol = Administrador, Vendedor, Tendero o Comprador; activo = 0 o 1'); END;
CREATE TRIGGER IF NOT EXISTS validar_pedidos_ins AFTER INSERT ON pedidos
WHEN NEW.estado NOT IN ('PENDIENTE', 'APROBADO', 'DESPACHADO', 'ENTREGADO', 'RECHAZADO', 'CANCELADO')
  OR NEW.tipo NOT IN ('MAYORISTA', 'TIENDA') OR typeof(NEW.total) NOT IN ('integer', 'real')
BEGIN SELECT RAISE(ABORT, 'Dato invalido en pedidos: estado, tipo o total no validos'); END;
CREATE TRIGGER IF NOT EXISTS validar_pedidos_upd AFTER UPDATE ON pedidos
WHEN NEW.estado NOT IN ('PENDIENTE', 'APROBADO', 'DESPACHADO', 'ENTREGADO', 'RECHAZADO', 'CANCELADO')
  OR NEW.tipo NOT IN ('MAYORISTA', 'TIENDA') OR typeof(NEW.total) NOT IN ('integer', 'real')
BEGIN SELECT RAISE(ABORT, 'Dato invalido en pedidos: estado, tipo o total no validos'); END;
CREATE TRIGGER IF NOT EXISTS validar_configuracion_ins AFTER INSERT ON configuracion
WHEN NEW.clave IN ('dias_alerta_vencimiento', 'stock_minimo_defecto') AND (NEW.valor = '' OR NEW.valor GLOB '*[^0-9]*')
BEGIN SELECT RAISE(ABORT, 'Dato invalido en configuracion: este parametro debe ser un numero entero'); END;
CREATE TRIGGER IF NOT EXISTS validar_configuracion_upd AFTER UPDATE ON configuracion
WHEN NEW.clave IN ('dias_alerta_vencimiento', 'stock_minimo_defecto') AND (NEW.valor = '' OR NEW.valor GLOB '*[^0-9]*')
BEGIN SELECT RAISE(ABORT, 'Dato invalido en configuracion: este parametro debe ser un numero entero'); END;
"""

USUARIOS_DEMO = [
    ("admin", "admin123", "Administrador", "Mayorista Central", "Calle 30, Barranquilla"),
    ("vendedor", "1234", "Vendedor", "Sede Principal", "Soledad Centro"),
    ("tendero", "1234", "Tendero", "Tienda Mi Barrio", "Cra 15 # 45-20, Soledad"),
    ("comprador", "1234", "Comprador", "Casa Familia Pérez", "Cra 8 # 30-15, Barranquilla"),
]


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
@contextmanager
def conexion():
    con = sqlite3.connect(DB_PATH, timeout=15)   # espera si otro programa (DBeaver) la tiene ocupada
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def hoy():
    return date.today()


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def dinero(valor):
    return "$" + f"{valor:,.0f}".replace(",", ".")


def validar_fecha(texto):
    try:
        return datetime.strptime(str(texto).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ErrorNegocio("La fecha debe tener el formato AAAA-MM-DD (ej. 2027-03-31).")


def validar_entero(valor, campo, minimo=0):
    try:
        n = int(str(valor).strip())
    except ValueError:
        raise ErrorNegocio(f"{campo} debe ser un número entero.")
    if n < minimo:
        raise ErrorNegocio(f"{campo} debe ser mayor o igual a {minimo}.")
    return n


def validar_numero(valor, campo):
    try:
        n = float(str(valor).strip())
    except ValueError:
        raise ErrorNegocio(f"{campo} debe ser un número (sin puntos de miles ni símbolos).")
    if n <= 0:
        raise ErrorNegocio(f"{campo} debe ser mayor que 0.")
    return n


def _vencido(fecha_iso):
    return date.fromisoformat(fecha_iso) < hoy()


def _hash_clave(clave, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(salt), 120_000).hex()
    return f"{salt}${h}"


_FORMATO_HASH = re.compile(r"[0-9a-f]{32}\$[0-9a-f]{64}")


def _clave_valida(clave, guardada):
    if not _FORMATO_HASH.fullmatch(guardada):      # clave escrita a mano en texto plano
        return hmac.compare_digest(guardada, clave)
    salt, h = guardada.split("$")
    return hmac.compare_digest(_hash_clave(clave, salt).split("$")[1], h)


def _mov(con, producto_id, producto, lote, tipo, cantidad, detalle, usuario):
    con.execute(
        "INSERT INTO movimientos (fecha, producto_id, producto, lote, tipo, cantidad, detalle, usuario)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (ahora(), producto_id, producto, lote, tipo, cantidad, detalle, usuario),
    )


def _merma(con, usuario_id, propietario, producto, lote, cantidad, costo, motivo, quien):
    con.execute(
        "INSERT INTO mermas (fecha, usuario_id, propietario, producto, lote, cantidad, costo_unitario, motivo, usuario)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (ahora(), usuario_id, propietario, producto, lote, cantidad, costo, motivo, quien),
    )


def _historial(con, pedido_id, estado, usuario, detalle=""):
    con.execute(
        "INSERT INTO historial_pedidos (pedido_id, estado, fecha, usuario, detalle) VALUES (?,?,?,?,?)",
        (pedido_id, estado, ahora(), usuario, detalle),
    )


# --------------------------------------------------------------------------
# Inicialización, versiones y respaldos
# --------------------------------------------------------------------------
def _preparar_archivo():
    """Devuelve True si la base es nueva. Si existe una base de una versión anterior
    (esquema incompatible) la conserva renombrándola y empieza una nueva."""
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        return True
    con = sqlite3.connect(DB_PATH)
    try:
        version = con.execute("PRAGMA user_version").fetchone()[0]
        tablas = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
    finally:
        con.close()
    if tablas == 0:
        return True
    if version >= SCHEMA_VERSION:
        return False
    base, ext = os.path.splitext(DB_PATH)
    os.replace(DB_PATH, f"{base}_anterior_{datetime.now():%Y%m%d_%H%M%S}{ext}")
    return True


def init_db(demo=True):
    """Crea la base si no existe. Los datos de demostración se cargan UNA sola vez,
    cuando la base es nueva: si luego borras productos, no vuelven a aparecer."""
    nueva = _preparar_archivo()
    with conexion() as con:
        con.executescript(SCHEMA)
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        con.execute("INSERT OR IGNORE INTO configuracion VALUES ('dias_alerta_vencimiento', '7')")
        con.execute("INSERT OR IGNORE INTO configuracion VALUES ('stock_minimo_defecto', '10')")
        if nueva:
            for u, c, rol, tienda, direc in USUARIOS_DEMO:
                con.execute(
                    "INSERT INTO usuarios (usuario, clave, rol, nombre_tienda, direccion) VALUES (?,?,?,?,?)",
                    (u, _hash_clave(c), rol, tienda, direc))
            if demo:
                # (nombre, lote, cantidad, mínimo, costo, p.mayorista, p.sugerido, días hasta vencer)
                for nom, lote, cant, minimo, costo, pm, ps, dias in [
                    ("Arroz Diana 500g", "A101", 120, 30, 1500, 1800, 2300, 180),
                    ("Aceite Girasol 1L", "B220", 15, 20, 8000, 9500, 11500, 240),
                    ("Leche en polvo 400g", "C330", 40, 15, 12500, 14500, 17000, 6),
                    ("Galletas Saltín", "D440", 60, 20, 1700, 2100, 2800, -3),
                    ("Azúcar 1kg", "E550", 0, 25, 2700, 3200, 4000, 300),
                    ("Pasta Doria 250g", "F660", 200, 40, 1100, 1400, 1900, 365),
                    ("Atún en lata 160g", "G770", 80, 25, 3500, 4200, 5200, 12),
                    ("Gaseosa 1.5L", "H880", 18, 24, 3100, 3800, 4800, 90)]:
                    cur = con.execute(
                        "INSERT INTO productos (nombre, lote, cantidad, stock_minimo, precio_costo, precio_mayorista,"
                        " precio_sugerido, fecha_vencimiento) VALUES (?,?,?,?,?,?,?,?)",
                        (nom, lote, cant, minimo, costo, pm, ps, (hoy() + timedelta(days=dias)).isoformat()))
                    if cant > 0:
                        _mov(con, cur.lastrowid, nom, lote, "ENTRADA", cant, "Carga inicial de demostración", "sistema")
        elif con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
            # Red de seguridad: sin usuarios nadie podría entrar al sistema.
            con.execute("INSERT INTO usuarios (usuario, clave, rol, nombre_tienda, direccion) VALUES (?,?,?,?,?)",
                        ("admin", _hash_clave("admin123"), "Administrador", "Mayorista Central", "Barranquilla"))
    if nueva and demo:
        _demo_pedidos()


def _demo_pedidos():
    """Un par de pedidos de ejemplo para que ganancias e inventario del tendero tengan datos."""
    try:
        t, v, c = autenticar("tendero", "1234"), autenticar("vendedor", "1234"), autenticar("comprador", "1234")
        prod = {p["nombre"]: p["id"] for p in listar_productos()}
        pid = crear_pedido(t, [(prod["Arroz Diana 500g"], 40, 2300), (prod["Pasta Doria 250g"], 30, 1900),
                               (prod["Leche en polvo 400g"], 10, 17000), (prod["Atún en lata 160g"], 15, 5200)])
        cambiar_estado(pid, "APROBADO", v)
        cambiar_estado(pid, "DESPACHADO", v)
        cambiar_estado(pid, "ENTREGADO", t)
        inv = {i["nombre_producto"]: i["id"] for i in inventario_tienda(t)}
        p2 = crear_pedido(c, [(inv["Arroz Diana 500g"], 6), (inv["Pasta Doria 250g"], 4)], tienda_id=t["id"])
        cambiar_estado(p2, "APROBADO", t)
        cambiar_estado(p2, "DESPACHADO", t)
        cambiar_estado(p2, "ENTREGADO", t)
    except (ErrorNegocio, KeyError):
        pass


def respaldar(max_copias=10):
    """Copia de seguridad de la base en la carpeta «respaldos» (conserva las últimas N)."""
    if not os.path.exists(DB_PATH):
        return None
    carpeta = os.path.join(os.path.dirname(DB_PATH), "respaldos")
    os.makedirs(carpeta, exist_ok=True)
    destino = os.path.join(carpeta, f"inventario_{datetime.now():%Y%m%d_%H%M%S_%f}.db")
    origen, copia = sqlite3.connect(DB_PATH), sqlite3.connect(destino)
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()
    for viejo in sorted(glob.glob(os.path.join(carpeta, "inventario_*.db")))[:-max_copias]:
        os.remove(viejo)
    return destino


def get_config(clave, defecto=None):
    with conexion() as con:
        fila = con.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
    return fila["valor"] if fila else defecto


def guardar_configuracion(dias_alerta, stock_minimo_defecto):
    dias = validar_entero(dias_alerta, "Los días de anticipación", 1)
    minimo = validar_entero(stock_minimo_defecto, "El stock mínimo por defecto", 0)
    with conexion() as con:
        con.execute("REPLACE INTO configuracion VALUES ('dias_alerta_vencimiento', ?)", (str(dias),))
        con.execute("REPLACE INTO configuracion VALUES ('stock_minimo_defecto', ?)", (str(minimo),))


def _dias_alerta():
    return int(get_config("dias_alerta_vencimiento", 7))


# --------------------------------------------------------------------------
# Usuarios
# --------------------------------------------------------------------------
def autenticar(usuario, clave):
    with conexion() as con:
        u = con.execute("SELECT * FROM usuarios WHERE usuario = ? AND activo = 1", (usuario.strip(),)).fetchone()
        if u and _clave_valida(clave, u["clave"]) and not _FORMATO_HASH.fullmatch(u["clave"]):
            # la contraseña se había escrito a mano en la base: se guarda cifrada desde ahora
            con.execute("UPDATE usuarios SET clave = ? WHERE id = ?", (_hash_clave(clave), u["id"]))
    if u and _clave_valida(clave, u["clave"]):
        return {"id": u["id"], "usuario": u["usuario"], "rol": u["rol"],
                "tienda": u["nombre_tienda"], "direccion": u["direccion"]}
    return None


def listar_usuarios():
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT id, usuario, rol, nombre_tienda, direccion, activo FROM usuarios ORDER BY id")]


def crear_usuario(usuario, clave, rol, tienda, direccion):
    usuario, tienda, direccion = usuario.strip(), tienda.strip(), direccion.strip()
    if not usuario or not tienda or not direccion:
        raise ErrorNegocio("Usuario, tienda y dirección son obligatorios.")
    if rol not in ROLES:
        raise ErrorNegocio("Selecciona un rol válido.")
    if len(clave) < 4:
        raise ErrorNegocio("La contraseña debe tener al menos 4 caracteres.")
    try:
        with conexion() as con:
            con.execute("INSERT INTO usuarios (usuario, clave, rol, nombre_tienda, direccion) VALUES (?,?,?,?,?)",
                        (usuario, _hash_clave(clave), rol, tienda, direccion))
    except sqlite3.IntegrityError:
        raise ErrorNegocio("Ya existe un usuario con ese nombre.")


def cambiar_clave(usuario_id, nueva):
    if len(nueva) < 4:
        raise ErrorNegocio("La contraseña debe tener al menos 4 caracteres.")
    with conexion() as con:
        con.execute("UPDATE usuarios SET clave = ? WHERE id = ?", (_hash_clave(nueva), usuario_id))


def set_activo(usuario_id, activo):
    with conexion() as con:
        con.execute("UPDATE usuarios SET activo = ? WHERE id = ?", (1 if activo else 0, usuario_id))


# --------------------------------------------------------------------------
# Inventario del mayorista
# --------------------------------------------------------------------------
def obtener_producto(producto_id):
    with conexion() as con:
        fila = con.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    return dict(fila) if fila else None


def listar_productos(filtro="", solo_disponibles=False):
    sql, params = "SELECT * FROM productos WHERE 1 = 1", []
    if solo_disponibles:
        sql += " AND cantidad > 0 AND fecha_vencimiento >= ?"
        params.append(hoy().isoformat())
    sql += " ORDER BY fecha_vencimiento, nombre"
    with conexion() as con:
        filas = [dict(r) for r in con.execute(sql, params)]
    if filtro:
        f = filtro.casefold()
        filas = [p for p in filas if f in f"{p['nombre']} {p['lote']}".casefold()]
    return filas


def _validar_precios(costo, p_mayorista, p_sugerido):
    c = validar_numero(costo, "El costo de compra")
    pm = validar_numero(p_mayorista, "El precio mayorista")
    ps = validar_numero(p_sugerido, "El precio sugerido")
    if pm < c:
        raise ErrorNegocio("El precio mayorista no puede ser menor al costo de compra.")
    if ps < pm:
        raise ErrorNegocio("El precio sugerido al público no puede ser menor al precio mayorista.")
    return c, pm, ps


def registrar_producto(nombre, lote, cantidad, stock_minimo, costo, p_mayorista, p_sugerido, vencimiento, usuario):
    nombre, lote = nombre.strip(), lote.strip()
    if not nombre or not lote:
        raise ErrorNegocio("El nombre y el lote son obligatorios.")
    cant = validar_entero(cantidad, "La cantidad", 1)
    minimo = validar_entero(stock_minimo, "El stock mínimo", 0)
    c, pm, ps = _validar_precios(costo, p_mayorista, p_sugerido)
    fecha = validar_fecha(vencimiento)
    if fecha < hoy():
        raise ErrorNegocio("No se puede registrar mercancía que ya está vencida.")
    with conexion() as con:
        if con.execute("SELECT 1 FROM productos WHERE nombre = ? AND lote = ?", (nombre, lote)).fetchone():
            raise ErrorNegocio("Ya existe ese producto con ese lote. Usa «Reponer stock» para sumar unidades.")
        cur = con.execute(
            "INSERT INTO productos (nombre, lote, cantidad, stock_minimo, precio_costo, precio_mayorista,"
            " precio_sugerido, fecha_vencimiento) VALUES (?,?,?,?,?,?,?,?)",
            (nombre, lote, cant, minimo, c, pm, ps, fecha.isoformat()))
        _mov(con, cur.lastrowid, nombre, lote, "ENTRADA", cant, "Registro inicial del lote", usuario)
        return cur.lastrowid


def reponer_stock(producto_id, cantidad, usuario):
    cant = validar_entero(cantidad, "La cantidad", 1)
    with conexion() as con:
        p = con.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
        if not p:
            raise ErrorNegocio("El producto no existe.")
        con.execute("UPDATE productos SET cantidad = cantidad + ? WHERE id = ?", (cant, producto_id))
        _mov(con, producto_id, p["nombre"], p["lote"], "ENTRADA", cant, "Reposición de stock", usuario)


def editar_producto(producto_id, stock_minimo, costo, p_mayorista, p_sugerido, vencimiento, usuario):
    minimo = validar_entero(stock_minimo, "El stock mínimo", 0)
    c, pm, ps = _validar_precios(costo, p_mayorista, p_sugerido)
    fecha = validar_fecha(vencimiento)
    with conexion() as con:
        p = con.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
        if not p:
            raise ErrorNegocio("El producto no existe.")
        con.execute(
            "UPDATE productos SET stock_minimo=?, precio_costo=?, precio_mayorista=?, precio_sugerido=?,"
            " fecha_vencimiento=? WHERE id = ?", (minimo, c, pm, ps, fecha.isoformat(), producto_id))
        _mov(con, producto_id, p["nombre"], p["lote"], "AJUSTE", 0, "Datos del producto editados", usuario)


def _pendientes_con_producto(con, tipo, producto_id, vendedor_id=None):
    sql = ("SELECT COUNT(*) FROM pedido_items i JOIN pedidos o ON o.id = i.pedido_id"
           " WHERE o.tipo = ? AND o.estado = 'PENDIENTE' AND i.producto_id = ?")
    params = [tipo, producto_id]
    if vendedor_id is not None:
        sql += " AND o.vendedor_id = ?"
        params.append(vendedor_id)
    return con.execute(sql, params).fetchone()[0]


def eliminar_producto(producto_id, usuario):
    """Borrado REAL: la fila desaparece de la tabla productos. El historial de pedidos y de
    movimientos se conserva porque guarda su propia copia de los datos del producto."""
    with conexion() as con:
        p = con.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
        if not p:
            raise ErrorNegocio("El producto no existe.")
        pend = _pendientes_con_producto(con, "MAYORISTA", producto_id)
        if pend:
            raise ErrorNegocio(f"Hay {pend} pedido(s) pendiente(s) con este producto. "
                               "Apruébalos, recházalos o cancélalos antes de eliminarlo.")
        con.execute("DELETE FROM productos WHERE id = ?", (producto_id,))
        _mov(con, producto_id, p["nombre"], p["lote"], "ELIMINADO", p["cantidad"], "Eliminado del inventario", usuario)


def retirar_vencido(producto_id, usuario):
    """Retira un lote vencido y registra la pérdida (unidades × costo). Devuelve el valor perdido."""
    with conexion() as con:
        p = con.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
        if not p:
            raise ErrorNegocio("El producto no existe.")
        if not _vencido(p["fecha_vencimiento"]):
            raise ErrorNegocio("Solo se pueden retirar como pérdida los productos que ya están vencidos.")
        pend = _pendientes_con_producto(con, "MAYORISTA", producto_id)
        if pend:
            raise ErrorNegocio(f"Hay {pend} pedido(s) pendiente(s) con este producto. Resuélvelos primero.")
        perdida = p["cantidad"] * p["precio_costo"]
        if p["cantidad"] > 0:
            _merma(con, None, "Mayorista", p["nombre"], p["lote"], p["cantidad"], p["precio_costo"], "Vencido", usuario)
        con.execute("DELETE FROM productos WHERE id = ?", (producto_id,))
        _mov(con, producto_id, p["nombre"], p["lote"], "MERMA", p["cantidad"], "Retirado por vencimiento", usuario)
        return perdida


# --------------------------------------------------------------------------
# Alertas
# --------------------------------------------------------------------------
def estados_producto(p, dias_alerta):
    """Devuelve (lista de alertas, días para vencer) de una fila de producto o de inventario de tienda."""
    dias = (date.fromisoformat(p["fecha_vencimiento"]) - hoy()).days
    est = []
    if p["cantidad"] > 0:
        if dias < 0:
            est.append("VENCIDO")
        elif dias <= dias_alerta:
            est.append("POR VENCER")
    if p["cantidad"] == 0:
        est.append("AGOTADO")
    elif p.get("stock_minimo") is not None and p["cantidad"] <= p["stock_minimo"]:
        est.append("STOCK BAJO")
    return est, dias


_ORDEN_ALERTA = {"VENCIDO": 0, "POR VENCER": 1, "AGOTADO": 2, "STOCK BAJO": 3}


def _armar_alertas(filas, nombre_key):
    dias_alerta, res = _dias_alerta(), []
    for p in filas:
        tipos, dias = estados_producto(p, dias_alerta)
        for t in tipos:
            res.append({"tipo": t, "id": p["id"], "nombre": p[nombre_key], "lote": p["lote"],
                        "cantidad": p["cantidad"], "stock_minimo": p.get("stock_minimo"),
                        "vencimiento": p["fecha_vencimiento"], "dias": dias})
    res.sort(key=lambda a: (_ORDEN_ALERTA[a["tipo"]], a["dias"]))
    return res


def alertas():
    """Alertas del inventario del mayorista."""
    return _armar_alertas(listar_productos(), "nombre")


def resumen_alertas():
    cuenta = {"VENCIDO": 0, "POR VENCER": 0, "AGOTADO": 0, "STOCK BAJO": 0}
    for a in alertas():
        cuenta[a["tipo"]] += 1
    return cuenta


def alertas_tienda(usuario):
    """Alertas de vencimiento del inventario de un tendero (solo productos con existencias)."""
    return _armar_alertas(inventario_tienda(usuario), "nombre_producto")


# --------------------------------------------------------------------------
# Inventario del tendero
# --------------------------------------------------------------------------
def inventario_tienda(usuario, solo_con_stock=True):
    sql = "SELECT * FROM inventario_tienda WHERE usuario_id = ?"
    if solo_con_stock:
        sql += " AND cantidad > 0"
    with conexion() as con:
        return [dict(r) for r in con.execute(sql + " ORDER BY fecha_vencimiento, nombre_producto", (usuario["id"],))]


def actualizar_precio_venta(usuario, item_id, precio):
    p = validar_numero(precio, "El precio de venta")
    with conexion() as con:
        cur = con.execute("UPDATE inventario_tienda SET precio_venta = ? WHERE id = ? AND usuario_id = ?",
                          (p, item_id, usuario["id"]))
        if cur.rowcount == 0:
            raise ErrorNegocio("Ese producto no está en tu inventario.")


def retirar_vencido_tienda(usuario, item_id):
    """El tendero retira un lote vencido de su inventario y registra la pérdida. Devuelve el valor perdido."""
    with conexion() as con:
        p = con.execute("SELECT * FROM inventario_tienda WHERE id = ? AND usuario_id = ?",
                        (item_id, usuario["id"])).fetchone()
        if not p:
            raise ErrorNegocio("Ese producto no está en tu inventario.")
        if not _vencido(p["fecha_vencimiento"]):
            raise ErrorNegocio("Solo se pueden retirar como pérdida los productos que ya están vencidos.")
        pend = _pendientes_con_producto(con, "TIENDA", item_id, usuario["id"])
        if pend:
            raise ErrorNegocio(f"Hay {pend} pedido(s) pendiente(s) con este producto. Resuélvelos primero.")
        perdida = p["cantidad"] * p["costo_unitario"]
        if p["cantidad"] > 0:
            _merma(con, usuario["id"], usuario["tienda"], p["nombre_producto"], p["lote"], p["cantidad"],
                   p["costo_unitario"], "Vencido", usuario["usuario"])
        con.execute("DELETE FROM inventario_tienda WHERE id = ?", (item_id,))
        return perdida


def listar_tiendas():
    """Tiendas donde un comprador puede comprar, con cuántos productos tienen disponibles."""
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT u.id, u.nombre_tienda, u.direccion, COUNT(i.id) AS productos FROM usuarios u"
            " LEFT JOIN inventario_tienda i ON i.usuario_id = u.id AND i.cantidad > 0 AND i.fecha_vencimiento >= ?"
            " WHERE u.activo = 1 AND u.rol IN ('Tendero', 'Administrador')"
            " GROUP BY u.id HAVING u.rol = 'Tendero' OR COUNT(i.id) > 0 ORDER BY u.nombre_tienda",
            (hoy().isoformat(),))]


def catalogo_tienda(tienda_id):
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM inventario_tienda WHERE usuario_id = ? AND cantidad > 0 AND fecha_vencimiento >= ?"
            " ORDER BY nombre_producto", (tienda_id, hoy().isoformat()))]


# --------------------------------------------------------------------------
# Pedidos
# --------------------------------------------------------------------------
def crear_pedido(usuario, items, nota="", tienda_id=None):
    """Sin tienda_id: pedido al MAYORISTA (items = (producto_id, cantidad, precio_publico)).
    Con tienda_id: compra a un TENDERO (items = (item_inventario_id, cantidad))."""
    rol = usuario["rol"]
    if tienda_id is None and rol not in ("Tendero", "Administrador"):
        raise ErrorNegocio("Solo los tenderos pueden pedir al mayorista. Los compradores compran en una tienda.")
    if tienda_id is not None and rol not in ("Comprador", "Administrador"):
        raise ErrorNegocio("Solo los compradores pueden comprar en una tienda.")
    if not items:
        raise ErrorNegocio("El pedido no tiene productos.")
    agrupado = {}
    for it in items:
        cant = validar_entero(it[1], "La cantidad", 1)
        pub = validar_numero(it[2], "El precio al público") if tienda_id is None else None
        acum = agrupado.setdefault(it[0], [0, pub])
        acum[0] += cant
        acum[1] = pub
    with conexion() as con:
        vendedor_id, vendedor = None, "Mayorista"
        if tienda_id is not None:
            if tienda_id == usuario["id"]:
                raise ErrorNegocio("No puedes comprarte a ti mismo.")
            t = con.execute("SELECT * FROM usuarios WHERE id = ? AND activo = 1 AND rol IN ('Tendero','Administrador')",
                            (tienda_id,)).fetchone()
            if not t:
                raise ErrorNegocio("La tienda seleccionada no está disponible.")
            vendedor_id, vendedor = t["id"], t["nombre_tienda"]
        lineas, total = [], 0.0
        for item_id, (cant, pub) in agrupado.items():
            if tienda_id is None:
                p = con.execute("SELECT * FROM productos WHERE id = ?", (item_id,)).fetchone()
                if p:
                    nombre, costo, precio = p["nombre"], p["precio_costo"], p["precio_mayorista"]
            else:
                p = con.execute("SELECT * FROM inventario_tienda WHERE id = ? AND usuario_id = ?",
                                (item_id, tienda_id)).fetchone()
                if p:
                    nombre, costo, precio = p["nombre_producto"], p["costo_unitario"], p["precio_venta"]
                    pub = precio
            if not p:
                raise ErrorNegocio("Un producto del pedido ya no está disponible.")
            if _vencido(p["fecha_vencimiento"]):
                raise ErrorNegocio(f"«{nombre}» (lote {p['lote']}) está vencido.")
            if cant > p["cantidad"]:
                raise ErrorNegocio(f"Stock insuficiente de «{nombre}» (lote {p['lote']}). Disponible: {p['cantidad']}.")
            lineas.append((item_id, nombre, p["lote"], p["fecha_vencimiento"], cant, costo, precio, pub))
            total += cant * precio
        cur = con.execute(
            "INSERT INTO pedidos (tipo, usuario_id, usuario, tienda, direccion, vendedor_id, vendedor, estado, total,"
            " fecha_creacion, nota) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MAYORISTA" if tienda_id is None else "TIENDA", usuario["id"], usuario["usuario"], usuario["tienda"],
             usuario["direccion"], vendedor_id, vendedor, "PENDIENTE", total, ahora(), nota.strip()))
        pedido_id = cur.lastrowid
        for item_id, nombre, lote, venc, cant, costo, precio, pub in lineas:
            con.execute(
                "INSERT INTO pedido_items (pedido_id, producto_id, nombre_producto, lote, fecha_vencimiento, cantidad,"
                " costo_unitario, precio_unitario, precio_publico) VALUES (?,?,?,?,?,?,?,?,?)",
                (pedido_id, item_id, nombre, lote, venc, cant, costo, precio, pub))
        _historial(con, pedido_id, "PENDIENTE", usuario["usuario"], "Pedido creado")
        return pedido_id


def cambiar_estado(pedido_id, nuevo, usuario, detalle=""):
    with conexion() as con:
        ped = con.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
        if not ped:
            raise ErrorNegocio("El pedido no existe.")
        if nuevo not in TRANSICIONES.get(ped["estado"], set()):
            raise ErrorNegocio(f"Un pedido {ped['estado']} no puede pasar a {nuevo}.")

        admin = usuario["rol"] == "Administrador"
        if nuevo in ACCIONES_VENDEDOR:       # lado del vendedor (mayorista o tendero)
            if ped["tipo"] == "MAYORISTA":
                permitido = admin or usuario["rol"] in ROLES_MAYORISTA
            else:
                permitido = admin or usuario["id"] == ped["vendedor_id"]
            if not permitido:
                raise ErrorNegocio("No tienes permiso para esta acción sobre este pedido.")
        else:                                 # lado del comprador: cancelar / confirmar recepción
            es_comprador = usuario["id"] == ped["usuario_id"]
            entrega_tienda = nuevo == "ENTREGADO" and ped["tipo"] == "TIENDA" and usuario["id"] == ped["vendedor_id"]
            if not (admin or es_comprador or entrega_tienda):
                raise ErrorNegocio("Solo quien hizo el pedido puede realizar esta acción.")

        items = con.execute("SELECT * FROM pedido_items WHERE pedido_id = ?", (pedido_id,)).fetchall()
        mayorista = ped["tipo"] == "MAYORISTA"

        if nuevo == "APROBADO":
            problemas = []
            for it in items:
                if mayorista:
                    s = con.execute("SELECT cantidad, fecha_vencimiento FROM productos WHERE id = ?",
                                    (it["producto_id"],)).fetchone()
                else:
                    s = con.execute("SELECT cantidad, fecha_vencimiento FROM inventario_tienda"
                                    " WHERE id = ? AND usuario_id = ?", (it["producto_id"], ped["vendedor_id"])).fetchone()
                desc = f"{it['nombre_producto']} (lote {it['lote']})"
                if s is None:
                    problemas.append(f"• {desc}: ya no existe en el inventario")
                elif s["cantidad"] < it["cantidad"]:
                    problemas.append(f"• {desc}: pide {it['cantidad']}, hay {s['cantidad']}")
                elif _vencido(s["fecha_vencimiento"]):
                    problemas.append(f"• {desc}: está vencido")
            if problemas:
                raise ErrorNegocio("No se puede aprobar el pedido:\n" + "\n".join(problemas))
            for it in items:
                if mayorista:
                    con.execute("UPDATE productos SET cantidad = cantidad - ? WHERE id = ?",
                                (it["cantidad"], it["producto_id"]))
                    _mov(con, it["producto_id"], it["nombre_producto"], it["lote"], "SALIDA", it["cantidad"],
                         f"Pedido #{pedido_id}", usuario["usuario"])
                else:
                    con.execute("UPDATE inventario_tienda SET cantidad = cantidad - ? WHERE id = ?",
                                (it["cantidad"], it["producto_id"]))

        elif nuevo == "ENTREGADO" and mayorista:
            # La mercancía entra al inventario del tendero, con su lote, vencimiento y costo.
            for it in items:
                con.execute(
                    "INSERT INTO inventario_tienda (usuario_id, nombre_producto, lote, fecha_vencimiento, cantidad,"
                    " costo_unitario, precio_venta) VALUES (?,?,?,?,?,?,?)"
                    " ON CONFLICT(usuario_id, nombre_producto, lote) DO UPDATE SET"
                    " costo_unitario = (cantidad * costo_unitario + excluded.cantidad * excluded.costo_unitario)"
                    " / (cantidad + excluded.cantidad),"
                    " cantidad = cantidad + excluded.cantidad, precio_venta = excluded.precio_venta",
                    (ped["usuario_id"], it["nombre_producto"], it["lote"], it["fecha_vencimiento"], it["cantidad"],
                     it["precio_unitario"], it["precio_publico"]))

        con.execute("UPDATE pedidos SET estado = ? WHERE id = ?", (nuevo, pedido_id))
        _historial(con, pedido_id, nuevo, usuario["usuario"], detalle)


def listar_pedidos(usuario, estados=None, como=None):
    """como='compras': lo que yo pedí/compré · como='ventas': lo que me piden a mí (tendero).
    Sin 'como': el administrador ve todo, el vendedor los pedidos al mayorista y los demás sus compras."""
    cond, params = ["1 = 1"], []
    if como == "ventas":
        cond.append("p.vendedor_id = ?")
        params.append(usuario["id"])
    elif como == "compras" or (como is None and usuario["rol"] in ("Tendero", "Comprador")):
        cond.append("p.usuario_id = ?")
        params.append(usuario["id"])
    elif como is None and usuario["rol"] == "Vendedor":
        cond.append("p.tipo = 'MAYORISTA'")
    elif como is None and usuario["rol"] != "Administrador":
        cond.append("0 = 1")
    if estados:
        cond.append(f"p.estado IN ({','.join('?' * len(estados))})")
        params += list(estados)
    sql = ("SELECT p.*, (SELECT GROUP_CONCAT(nombre_producto || ' x' || cantidad, ', ') FROM pedido_items"
           " WHERE pedido_id = p.id) AS resumen FROM pedidos p WHERE " + " AND ".join(cond) + " ORDER BY p.id DESC")
    with conexion() as con:
        return [dict(r) for r in con.execute(sql, params)]


def obtener_pedido(pedido_id):
    with conexion() as con:
        fila = con.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
    return dict(fila) if fila else None


def items_pedido(pedido_id):
    with conexion() as con:
        return [dict(r) for r in con.execute("SELECT * FROM pedido_items WHERE pedido_id = ?", (pedido_id,))]


def historial_pedido(pedido_id):
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM historial_pedidos WHERE pedido_id = ? ORDER BY id", (pedido_id,))]


# --------------------------------------------------------------------------
# Ganancias, panel y reportes
# --------------------------------------------------------------------------
def ganancias(usuario, ambito="mayorista", desde=None):
    """ambito='mayorista': ventas del mayorista a tenderos · ambito='tienda': ventas del tendero a compradores.
    desde: fecha AAAA-MM-DD (opcional). Ganancia bruta = ventas − costo; neta = bruta − pérdidas por vencimiento."""
    if ambito == "mayorista":
        filtro, params = "p.tipo = 'MAYORISTA'", []
        filtro_merma, params_merma = "usuario_id IS NULL", []
    else:
        filtro, params = "p.tipo = 'TIENDA' AND p.vendedor_id = ?", [usuario["id"]]
        filtro_merma, params_merma = "usuario_id = ?", [usuario["id"]]
    if desde:
        filtro += " AND p.fecha_creacion >= ?"
        params.append(desde)
        filtro_merma += " AND fecha >= ?"
        params_merma.append(desde)
    with conexion() as con:
        filas = [dict(r) for r in con.execute(
            "SELECT i.nombre_producto AS producto, SUM(i.cantidad) AS unidades,"
            " SUM(i.cantidad * i.precio_unitario) AS ventas, SUM(i.cantidad * i.costo_unitario) AS costo"
            " FROM pedido_items i JOIN pedidos p ON p.id = i.pedido_id"
            f" WHERE {filtro} AND p.estado IN ('APROBADO', 'DESPACHADO', 'ENTREGADO')"
            " GROUP BY i.nombre_producto ORDER BY (SUM(i.cantidad * i.precio_unitario)"
            " - SUM(i.cantidad * i.costo_unitario)) DESC", params)]
        perdidas = con.execute(f"SELECT COALESCE(SUM(cantidad * costo_unitario), 0) FROM mermas WHERE {filtro_merma}",
                               params_merma).fetchone()[0]
    for f in filas:
        f["ganancia"] = f["ventas"] - f["costo"]
        f["margen"] = (f["ganancia"] / f["ventas"] * 100) if f["ventas"] else 0.0
    ventas, costo = sum(f["ventas"] for f in filas), sum(f["costo"] for f in filas)
    bruta = ventas - costo
    return {"filas": filas, "unidades": sum(f["unidades"] for f in filas), "ventas": ventas, "costo": costo,
            "ganancia_bruta": bruta, "perdidas": perdidas, "ganancia_neta": bruta - perdidas,
            "margen": (bruta / ventas * 100) if ventas else 0.0}


def reporte_mermas(usuario=None, desde=None):
    """Pérdidas por vencimiento. usuario=None → las del mayorista; con usuario → las de su tienda."""
    sql, params = "SELECT * FROM mermas WHERE ", []
    if usuario is None:
        sql += "usuario_id IS NULL"
    else:
        sql += "usuario_id = ?"
        params.append(usuario["id"])
    if desde:
        sql += " AND fecha >= ?"
        params.append(desde)
    with conexion() as con:
        return [dict(r) for r in con.execute(sql + " ORDER BY id DESC", params)]


def reporte_mas_solicitados(limite=15):
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT i.nombre_producto AS producto, SUM(i.cantidad) AS unidades,"
            " COUNT(DISTINCT i.pedido_id) AS pedidos, SUM(i.cantidad * i.precio_unitario) AS valor"
            " FROM pedido_items i JOIN pedidos p ON p.id = i.pedido_id"
            " WHERE p.tipo = 'MAYORISTA' AND p.estado NOT IN ('RECHAZADO', 'CANCELADO')"
            " GROUP BY i.nombre_producto ORDER BY unidades DESC LIMIT ?", (limite,))]


def reporte_pedidos_por_estado():
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT estado, COUNT(*) AS cantidad, SUM(total) AS total FROM pedidos"
            " WHERE tipo = 'MAYORISTA' GROUP BY estado")]


def reporte_movimientos(limite=300):
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT fecha, producto, lote, tipo, cantidad, detalle, usuario FROM movimientos"
            " ORDER BY id DESC LIMIT ?", (limite,))]


def resumen_general():
    with conexion() as con:
        inv = con.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(cantidad), 0) u, COALESCE(SUM(cantidad * precio_costo), 0) costo,"
            " COALESCE(SUM(cantidad * precio_mayorista), 0) venta FROM productos").fetchone()
        pend = con.execute("SELECT COUNT(*) FROM pedidos WHERE tipo = 'MAYORISTA' AND estado = 'PENDIENTE'").fetchone()[0]
    g = ganancias(None, "mayorista")
    return [("Lotes de productos", inv["n"]),
            ("Unidades en bodega", inv["u"]),
            ("Valor del inventario (a costo)", dinero(inv["costo"])),
            ("Valor del inventario (a precio mayorista)", dinero(inv["venta"])),
            ("Pedidos pendientes por aprobar", pend),
            ("Ventas aprobadas (acumulado)", dinero(g["ventas"])),
            ("Ganancia bruta (acumulado)", dinero(g["ganancia_bruta"])),
            ("Pérdidas por vencimiento (acumulado)", dinero(g["perdidas"]))]


def panel(usuario):
    """Indicadores de la pantalla de inicio según el rol."""
    rol, mes = usuario["rol"], hoy().replace(day=1).isoformat()
    t = lambda titulo, valor, nivel="info": {"titulo": titulo, "valor": valor, "nivel": nivel}
    if rol in ROLES_MAYORISTA:
        with conexion() as con:
            inv = con.execute("SELECT COUNT(*) n, COALESCE(SUM(cantidad), 0) u,"
                              " COALESCE(SUM(cantidad * precio_costo), 0) costo FROM productos").fetchone()
        pend, n_alertas = len(listar_pedidos(usuario, ["PENDIENTE"])), sum(resumen_alertas().values())
        g = ganancias(None, "mayorista", mes)
        return [t("Lotes en inventario", inv["n"]), t("Unidades en bodega", inv["u"]),
                t("Valor del inventario (a costo)", dinero(inv["costo"])),
                t("Pedidos por aprobar", pend, "aviso" if pend else "ok"),
                t("Alertas activas", n_alertas, "malo" if n_alertas else "ok"),
                t("Ganancia bruta del mes", dinero(g["ganancia_bruta"]), "ok")]
    if rol == "Tendero":
        inv = inventario_tienda(usuario)
        costo = sum(i["cantidad"] * i["costo_unitario"] for i in inv)
        potencial = sum(i["cantidad"] * (i["precio_venta"] - i["costo_unitario"]) for i in inv if not _vencido(i["fecha_vencimiento"]))
        pend, n_alertas = len(listar_pedidos(usuario, ["PENDIENTE"], "ventas")), len(alertas_tienda(usuario))
        g = ganancias(usuario, "tienda", mes)
        return [t("Valor de mi inventario (a costo)", dinero(costo)),
                t("Ganancia potencial en inventario", dinero(potencial), "ok"),
                t("Ventas por aprobar", pend, "aviso" if pend else "ok"),
                t("Productos vencidos o por vencer", n_alertas, "malo" if n_alertas else "ok"),
                t("Ganancia bruta del mes", dinero(g["ganancia_bruta"]), "ok"),
                t("Pérdidas por vencimiento (mes)", dinero(g["perdidas"]), "malo" if g["perdidas"] else "ok")]
    mis = listar_pedidos(usuario)
    return [t("Tiendas con productos", sum(1 for x in listar_tiendas() if x["productos"] > 0)),
            t("Mis pedidos en curso", sum(1 for p in mis if p["estado"] in ESTADOS_ACTIVOS), "aviso"),
            t("Total gastado", dinero(sum(p["total"] for p in mis if p["estado"] in ESTADOS_VENTA)), "info")]


def exportar_csv(ruta, columnas, filas):
    # utf-8-sig y ';' para que Excel en español lo abra correctamente
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(columnas)
        w.writerows(filas)
