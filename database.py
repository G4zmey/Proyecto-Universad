"""Capa de datos y reglas de negocio del Sistema de Inventario Mayorista.

Esta capa NO usa Tkinter: toda la lógica (validaciones, estados de pedidos,
alertas, reportes) vive aquí para poder probarla de forma automática.
"""
import csv
import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "inventario_mayorista_v2.db")

ROLES = ("Administrador", "Vendedor", "Tendero", "Comprador")
ROLES_MAYORISTA = ("Administrador", "Vendedor")
ROLES_MINORISTA = ("Tendero", "Comprador")
# El Administrador también puede hacer pedidos y actuar como tendero (útil para probar todo el sistema)
ROLES_PEDIDO = ROLES_MINORISTA + ("Administrador",)

ESTADOS_ACTIVOS = ("PENDIENTE", "APROBADO", "DESPACHADO")
ESTADOS_FINALES = ("ENTREGADO", "RECHAZADO", "CANCELADO")
TRANSICIONES = {
    "PENDIENTE": {"APROBADO", "RECHAZADO", "CANCELADO"},
    "APROBADO": {"DESPACHADO"},
    "DESPACHADO": {"ENTREGADO"},
}
ACCIONES_MAYORISTA = {"APROBADO", "RECHAZADO", "DESPACHADO"}


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
CREATE TABLE IF NOT EXISTS productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL COLLATE NOCASE,
    lote TEXT NOT NULL COLLATE NOCASE,
    cantidad INTEGER NOT NULL CHECK (cantidad >= 0),
    stock_minimo INTEGER NOT NULL DEFAULT 10,
    precio_mayorista REAL NOT NULL,
    precio_sugerido REAL NOT NULL,
    fecha_vencimiento TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    UNIQUE (nombre, lote)
);
CREATE TABLE IF NOT EXISTS pedidos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    usuario TEXT NOT NULL,
    tienda TEXT NOT NULL,
    direccion TEXT NOT NULL,
    estado TEXT NOT NULL,
    total REAL NOT NULL,
    fecha_creacion TEXT NOT NULL,
    nota TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pedido_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id INTEGER NOT NULL REFERENCES pedidos(id),
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    nombre_producto TEXT NOT NULL,
    lote TEXT NOT NULL,
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL,
    precio_publico REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS historial_pedidos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id INTEGER NOT NULL REFERENCES pedidos(id),
    estado TEXT NOT NULL,
    fecha TEXT NOT NULL,
    usuario TEXT NOT NULL,
    detalle TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS inventario_tienda (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    nombre_producto TEXT NOT NULL COLLATE NOCASE,
    cantidad INTEGER NOT NULL,
    precio_venta REAL NOT NULL,
    UNIQUE (usuario_id, nombre_producto)
);
CREATE TABLE IF NOT EXISTS movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    producto_id INTEGER REFERENCES productos(id),
    tipo TEXT NOT NULL,
    cantidad INTEGER NOT NULL,
    detalle TEXT NOT NULL DEFAULT '',
    usuario TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
"""

USUARIOS_DEMO = [
    ("admin", "admin123", "Administrador", "Mayorista Central", "Calle 30, Barranquilla"),
    ("vendedor", "1234", "Vendedor", "Sede Principal", "Soledad Centro"),
    ("tendero", "1234", "Tendero", "Tienda Mi Barrio", "Cra 15 # 45-20, Soledad"),
    ("comprador", "1234", "Comprador", "Minimercado La Esquina", "Cra 8 # 30-15, Barranquilla"),
]


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
@contextmanager
def conexion():
    con = sqlite3.connect(DB_PATH)
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


def _hash_clave(clave, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(salt), 120_000).hex()
    return f"{salt}${h}"


def _clave_valida(clave, guardada):
    salt, h = guardada.split("$")
    return hmac.compare_digest(_hash_clave(clave, salt).split("$")[1], h)


def _mov(con, producto_id, tipo, cantidad, detalle, usuario):
    con.execute(
        "INSERT INTO movimientos (fecha, producto_id, tipo, cantidad, detalle, usuario) VALUES (?,?,?,?,?,?)",
        (ahora(), producto_id, tipo, cantidad, detalle, usuario),
    )


def _historial(con, pedido_id, estado, usuario, detalle=""):
    con.execute(
        "INSERT INTO historial_pedidos (pedido_id, estado, fecha, usuario, detalle) VALUES (?,?,?,?,?)",
        (pedido_id, estado, ahora(), usuario, detalle),
    )


# --------------------------------------------------------------------------
# Inicialización y configuración
# --------------------------------------------------------------------------
def init_db(demo=True):
    with conexion() as con:
        con.executescript(SCHEMA)
        con.execute("INSERT OR IGNORE INTO configuracion VALUES ('dias_alerta_vencimiento', '15')")
        con.execute("INSERT OR IGNORE INTO configuracion VALUES ('stock_minimo_defecto', '10')")
        if con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
            for u, c, rol, tienda, direc in USUARIOS_DEMO:
                con.execute(
                    "INSERT INTO usuarios (usuario, clave, rol, nombre_tienda, direccion) VALUES (?,?,?,?,?)",
                    (u, _hash_clave(c), rol, tienda, direc),
                )
        if demo and con.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 0:
            # (nombre, lote, cantidad, mínimo, p.mayorista, p.sugerido, días hasta vencer)
            demo_prod = [
                ("Arroz Diana 500g", "A101", 120, 30, 1800, 2300, 180),
                ("Aceite Girasol 1L", "B220", 15, 20, 9500, 11500, 240),
                ("Leche en polvo 400g", "C330", 40, 15, 14500, 17000, 6),
                ("Galletas Saltín", "D440", 60, 20, 2100, 2800, -3),
                ("Azúcar 1kg", "E550", 0, 25, 3200, 4000, 300),
                ("Pasta Doria 250g", "F660", 200, 40, 1400, 1900, 365),
                ("Atún en lata 160g", "G770", 80, 25, 4200, 5200, 12),
                ("Gaseosa 1.5L", "H880", 18, 24, 3800, 4800, 90),
            ]
            for nom, lote, cant, minimo, pm, ps, dias in demo_prod:
                venc = (hoy() + timedelta(days=dias)).isoformat()
                cur = con.execute(
                    "INSERT INTO productos (nombre, lote, cantidad, stock_minimo, precio_mayorista,"
                    " precio_sugerido, fecha_vencimiento) VALUES (?,?,?,?,?,?,?)",
                    (nom, lote, cant, minimo, pm, ps, venc),
                )
                if cant > 0:
                    _mov(con, cur.lastrowid, "ENTRADA", cant, "Carga inicial de demostración", "sistema")


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


# --------------------------------------------------------------------------
# Usuarios
# --------------------------------------------------------------------------
def autenticar(usuario, clave):
    with conexion() as con:
        u = con.execute(
            "SELECT * FROM usuarios WHERE usuario = ? AND activo = 1", (usuario.strip(),)
        ).fetchone()
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
            con.execute(
                "INSERT INTO usuarios (usuario, clave, rol, nombre_tienda, direccion) VALUES (?,?,?,?,?)",
                (usuario, _hash_clave(clave), rol, tienda, direccion),
            )
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
# Productos e inventario mayorista
# --------------------------------------------------------------------------
def obtener_producto(producto_id):
    with conexion() as con:
        fila = con.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    return dict(fila) if fila else None


def listar_productos(filtro="", solo_disponibles=False):
    sql = "SELECT * FROM productos WHERE activo = 1"
    params = []
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


def registrar_producto(nombre, lote, cantidad, stock_minimo, p_mayorista, p_sugerido, vencimiento, usuario):
    nombre, lote = nombre.strip(), lote.strip()
    if not nombre or not lote:
        raise ErrorNegocio("El nombre y el lote son obligatorios.")
    cant = validar_entero(cantidad, "La cantidad", 1)
    minimo = validar_entero(stock_minimo, "El stock mínimo", 0)
    pm = validar_numero(p_mayorista, "El precio mayorista")
    ps = validar_numero(p_sugerido, "El precio sugerido")
    if ps < pm:
        raise ErrorNegocio("El precio sugerido al público no puede ser menor al precio mayorista.")
    fecha = validar_fecha(vencimiento)
    if fecha < hoy():
        raise ErrorNegocio("No se puede registrar mercancía que ya está vencida.")
    with conexion() as con:
        previo = con.execute("SELECT id, activo FROM productos WHERE nombre = ? AND lote = ?", (nombre, lote)).fetchone()
        if previo and previo["activo"]:
            raise ErrorNegocio("Ya existe ese producto con ese lote. Usa «Reponer stock» para sumar unidades.")
        if previo:  # estaba dado de baja: se reactiva con los datos nuevos y se conserva su historial
            con.execute(
                "UPDATE productos SET cantidad=?, stock_minimo=?, precio_mayorista=?, precio_sugerido=?,"
                " fecha_vencimiento=?, activo=1 WHERE id=?",
                (cant, minimo, pm, ps, fecha.isoformat(), previo["id"]),
            )
            _mov(con, previo["id"], "ENTRADA", cant, "Reingreso de un producto dado de baja", usuario)
            return previo["id"]
        cur = con.execute(
            "INSERT INTO productos (nombre, lote, cantidad, stock_minimo, precio_mayorista,"
            " precio_sugerido, fecha_vencimiento) VALUES (?,?,?,?,?,?,?)",
            (nombre, lote, cant, minimo, pm, ps, fecha.isoformat()),
        )
        _mov(con, cur.lastrowid, "ENTRADA", cant, "Registro inicial del lote", usuario)
        return cur.lastrowid


def reponer_stock(producto_id, cantidad, usuario):
    cant = validar_entero(cantidad, "La cantidad", 1)
    with conexion() as con:
        if not con.execute("SELECT 1 FROM productos WHERE id = ? AND activo = 1", (producto_id,)).fetchone():
            raise ErrorNegocio("El producto no existe o está dado de baja.")
        con.execute("UPDATE productos SET cantidad = cantidad + ? WHERE id = ?", (cant, producto_id))
        _mov(con, producto_id, "ENTRADA", cant, "Reposición de stock", usuario)


def editar_producto(producto_id, stock_minimo, p_mayorista, p_sugerido, vencimiento, usuario):
    minimo = validar_entero(stock_minimo, "El stock mínimo", 0)
    pm = validar_numero(p_mayorista, "El precio mayorista")
    ps = validar_numero(p_sugerido, "El precio sugerido")
    if ps < pm:
        raise ErrorNegocio("El precio sugerido al público no puede ser menor al precio mayorista.")
    fecha = validar_fecha(vencimiento)
    with conexion() as con:
        con.execute(
            "UPDATE productos SET stock_minimo=?, precio_mayorista=?, precio_sugerido=?, fecha_vencimiento=?"
            " WHERE id = ? AND activo = 1",
            (minimo, pm, ps, fecha.isoformat(), producto_id),
        )
        _mov(con, producto_id, "AJUSTE", 0, "Datos del producto editados", usuario)


def dar_de_baja(producto_id, usuario):
    """Baja lógica: el producto sale del catálogo pero se conserva su historial."""
    with conexion() as con:
        p = con.execute("SELECT cantidad FROM productos WHERE id = ? AND activo = 1", (producto_id,)).fetchone()
        if not p:
            raise ErrorNegocio("El producto no existe o ya está dado de baja.")
        con.execute("UPDATE productos SET activo = 0 WHERE id = ?", (producto_id,))
        _mov(con, producto_id, "BAJA", p["cantidad"], "Producto dado de baja del catálogo", usuario)


# --------------------------------------------------------------------------
# Alertas
# --------------------------------------------------------------------------
def estados_producto(p, dias_alerta):
    """Devuelve (lista de alertas, días para vencer) de un producto."""
    dias = (date.fromisoformat(p["fecha_vencimiento"]) - hoy()).days
    est = []
    if p["cantidad"] > 0:
        if dias < 0:
            est.append("VENCIDO")
        elif dias <= dias_alerta:
            est.append("POR VENCER")
    if p["cantidad"] == 0:
        est.append("AGOTADO")
    elif p["cantidad"] <= p["stock_minimo"]:
        est.append("STOCK BAJO")
    return est, dias


def alertas():
    dias_alerta = int(get_config("dias_alerta_vencimiento", 15))
    orden = {"VENCIDO": 0, "POR VENCER": 1, "AGOTADO": 2, "STOCK BAJO": 3}
    res = []
    for p in listar_productos():
        tipos, dias = estados_producto(p, dias_alerta)
        for t in tipos:
            res.append({"tipo": t, "id": p["id"], "nombre": p["nombre"], "lote": p["lote"],
                        "cantidad": p["cantidad"], "stock_minimo": p["stock_minimo"],
                        "vencimiento": p["fecha_vencimiento"], "dias": dias})
    res.sort(key=lambda a: (orden[a["tipo"]], a["dias"]))
    return res


def resumen_alertas():
    cuenta = {"VENCIDO": 0, "POR VENCER": 0, "AGOTADO": 0, "STOCK BAJO": 0}
    for a in alertas():
        cuenta[a["tipo"]] += 1
    return cuenta


# --------------------------------------------------------------------------
# Pedidos
# --------------------------------------------------------------------------
def crear_pedido(usuario, items, nota=""):
    """items: lista de (producto_id, cantidad, precio_publico)."""
    if usuario["rol"] not in ROLES_PEDIDO:
        raise ErrorNegocio("Tu rol no puede crear pedidos.")
    if not items:
        raise ErrorNegocio("El pedido no tiene productos.")
    agrupado = {}
    for pid, cant, pub in items:
        cant = validar_entero(cant, "La cantidad", 1)
        pub = validar_numero(pub, "El precio al público")
        acum = agrupado.setdefault(pid, [0, pub])
        acum[0] += cant
        acum[1] = pub
    with conexion() as con:
        lineas, total = [], 0.0
        for pid, (cant, pub) in agrupado.items():
            p = con.execute("SELECT * FROM productos WHERE id = ? AND activo = 1", (pid,)).fetchone()
            if not p:
                raise ErrorNegocio("Un producto del pedido ya no está disponible.")
            if date.fromisoformat(p["fecha_vencimiento"]) < hoy():
                raise ErrorNegocio(f"«{p['nombre']}» (lote {p['lote']}) está vencido.")
            if cant > p["cantidad"]:
                raise ErrorNegocio(
                    f"Stock insuficiente de «{p['nombre']}» (lote {p['lote']}). Disponible: {p['cantidad']}.")
            lineas.append((pid, p["nombre"], p["lote"], cant, p["precio_mayorista"], pub))
            total += cant * p["precio_mayorista"]
        cur = con.execute(
            "INSERT INTO pedidos (usuario_id, usuario, tienda, direccion, estado, total, fecha_creacion, nota)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (usuario["id"], usuario["usuario"], usuario["tienda"], usuario["direccion"],
             "PENDIENTE", total, ahora(), nota.strip()),
        )
        pedido_id = cur.lastrowid
        for pid, nom, lote, cant, pu, pub in lineas:
            con.execute(
                "INSERT INTO pedido_items (pedido_id, producto_id, nombre_producto, lote, cantidad,"
                " precio_unitario, precio_publico) VALUES (?,?,?,?,?,?,?)",
                (pedido_id, pid, nom, lote, cant, pu, pub),
            )
        _historial(con, pedido_id, "PENDIENTE", usuario["usuario"], "Pedido creado")
        return pedido_id


def cambiar_estado(pedido_id, nuevo, usuario, detalle=""):
    with conexion() as con:
        ped = con.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
        if not ped:
            raise ErrorNegocio("El pedido no existe.")
        if nuevo not in TRANSICIONES.get(ped["estado"], set()):
            raise ErrorNegocio(f"Un pedido {ped['estado']} no puede pasar a {nuevo}.")
        if nuevo in ACCIONES_MAYORISTA:
            if usuario["rol"] not in ROLES_MAYORISTA:
                raise ErrorNegocio("Solo el personal del mayorista puede realizar esta acción.")
        elif usuario["rol"] != "Administrador" and (
                usuario["rol"] not in ROLES_MINORISTA or ped["usuario_id"] != usuario["id"]):
            raise ErrorNegocio("Solo quien hizo el pedido puede realizar esta acción.")

        items = con.execute("SELECT * FROM pedido_items WHERE pedido_id = ?", (pedido_id,)).fetchall()

        if nuevo == "APROBADO":
            problemas = []
            for it in items:
                p = con.execute("SELECT * FROM productos WHERE id = ?", (it["producto_id"],)).fetchone()
                if p["cantidad"] < it["cantidad"]:
                    problemas.append(f"• {p['nombre']} (lote {p['lote']}): pide {it['cantidad']}, hay {p['cantidad']}")
                elif date.fromisoformat(p["fecha_vencimiento"]) < hoy():
                    problemas.append(f"• {p['nombre']} (lote {p['lote']}): está vencido")
            if problemas:
                raise ErrorNegocio("No se puede aprobar el pedido:\n" + "\n".join(problemas))
            for it in items:
                con.execute("UPDATE productos SET cantidad = cantidad - ? WHERE id = ?",
                            (it["cantidad"], it["producto_id"]))
                _mov(con, it["producto_id"], "SALIDA", it["cantidad"], f"Pedido #{pedido_id}", usuario["usuario"])

        elif nuevo == "ENTREGADO":
            for it in items:
                con.execute(
                    "INSERT INTO inventario_tienda (usuario_id, nombre_producto, cantidad, precio_venta)"
                    " VALUES (?,?,?,?) ON CONFLICT(usuario_id, nombre_producto) DO UPDATE SET"
                    " cantidad = cantidad + excluded.cantidad, precio_venta = excluded.precio_venta",
                    (ped["usuario_id"], it["nombre_producto"], it["cantidad"], it["precio_publico"]),
                )

        con.execute("UPDATE pedidos SET estado = ? WHERE id = ?", (nuevo, pedido_id))
        _historial(con, pedido_id, nuevo, usuario["usuario"], detalle)


def listar_pedidos(usuario, estados=None):
    sql = ("SELECT p.*, (SELECT GROUP_CONCAT(nombre_producto || ' x' || cantidad, ', ')"
           " FROM pedido_items WHERE pedido_id = p.id) AS resumen FROM pedidos p WHERE 1=1")
    params = []
    if usuario["rol"] in ROLES_MINORISTA:
        sql += " AND p.usuario_id = ?"
        params.append(usuario["id"])
    if estados:
        sql += f" AND p.estado IN ({','.join('?' * len(estados))})"
        params += list(estados)
    sql += " ORDER BY p.id DESC"
    with conexion() as con:
        return [dict(r) for r in con.execute(sql, params)]


def items_pedido(pedido_id):
    with conexion() as con:
        return [dict(r) for r in con.execute("SELECT * FROM pedido_items WHERE pedido_id = ?", (pedido_id,))]


def historial_pedido(pedido_id):
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM historial_pedidos WHERE pedido_id = ? ORDER BY id", (pedido_id,))]


def inventario_tienda(usuario):
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM inventario_tienda WHERE usuario_id = ? ORDER BY nombre_producto", (usuario["id"],))]


# --------------------------------------------------------------------------
# Reportes
# --------------------------------------------------------------------------
def reporte_mas_solicitados(limite=15):
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT i.nombre_producto AS producto, SUM(i.cantidad) AS unidades,"
            " COUNT(DISTINCT i.pedido_id) AS pedidos, SUM(i.cantidad * i.precio_unitario) AS valor"
            " FROM pedido_items i JOIN pedidos p ON p.id = i.pedido_id"
            " WHERE p.estado NOT IN ('RECHAZADO', 'CANCELADO')"
            " GROUP BY i.nombre_producto ORDER BY unidades DESC LIMIT ?", (limite,))]


def reporte_pedidos_por_estado():
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT estado, COUNT(*) AS cantidad, SUM(total) AS total FROM pedidos GROUP BY estado")]


def reporte_movimientos(limite=300):
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT m.fecha, COALESCE(p.nombre, '-') AS producto, COALESCE(p.lote, '-') AS lote,"
            " m.tipo, m.cantidad, m.detalle, m.usuario FROM movimientos m"
            " LEFT JOIN productos p ON p.id = m.producto_id ORDER BY m.id DESC LIMIT ?", (limite,))]


def resumen_general():
    with conexion() as con:
        inv = con.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(cantidad), 0) u,"
            " COALESCE(SUM(cantidad * precio_mayorista), 0) v FROM productos WHERE activo = 1").fetchone()
        pend = con.execute("SELECT COUNT(*) FROM pedidos WHERE estado = 'PENDIENTE'").fetchone()[0]
        ventas = con.execute(
            "SELECT COALESCE(SUM(total), 0) FROM pedidos"
            " WHERE estado IN ('APROBADO', 'DESPACHADO', 'ENTREGADO')").fetchone()[0]
    return [("Lotes de productos activos", inv["n"]),
            ("Unidades en bodega", inv["u"]),
            ("Valor del inventario (precio mayorista)", dinero(inv["v"])),
            ("Pedidos pendientes por aprobar", pend),
            ("Ventas aprobadas (acumulado)", dinero(ventas))]


def exportar_csv(ruta, columnas, filas):
    # utf-8-sig y ';' para que Excel en español lo abra correctamente
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(columnas)
        w.writerows(filas)
