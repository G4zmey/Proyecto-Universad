"""SysMayor — Sistema de Inventario y Pedidos para distribuidoras mayoristas (interfaz Tkinter).

Ejecutar:  python main.py
Las reglas de negocio están en database.py; aquí solo hay interfaz.
"""
import sqlite3
import tkinter as tk
from datetime import date, timedelta
from tkinter import filedialog, messagebox, simpledialog, ttk

import database as db

# ---------------------------------------------------------------- estilo
FONDO, BLANCO, BORDE, TEXTO, GRIS = "#f3f4f6", "#ffffff", "#e5e7eb", "#111827", "#6b7280"
LATERAL, LATERAL_HOVER, LATERAL_ACTIVO = "#111827", "#1f2937", "#2563eb"
COLORES = {"primario": "#2563eb", "exito": "#16a34a", "peligro": "#dc2626",
           "aviso": "#d97706", "neutro": "#6b7280", "info": "#0891b2"}
NIVELES = {"ok": "#16a34a", "aviso": "#d97706", "malo": "#dc2626", "info": "#2563eb"}
ALERTAS_COLOR = {"VENCIDO": "#fecaca", "POR VENCER": "#fed7aa", "AGOTADO": "#e5e7eb", "STOCK BAJO": "#fef08a"}
FUENTE, FUENTE_B = ("Segoe UI", 10), ("Segoe UI", 10, "bold")
TITULO, SUBTITULO = ("Segoe UI", 19, "bold"), ("Segoe UI", 10)


def oscurecer(color, factor=0.85):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r * factor), int(g * factor), int(b * factor))


def tag_de(tipo):
    return tipo.replace(" ", "_")


def texto_dias(d):
    return f"vencido hace {-d} d" if d < 0 else ("vence hoy" if d == 0 else f"faltan {d} d")


class Boton(tk.Label):
    """Botón plano con efecto al pasar el mouse (funciona igual en Windows, Mac y Linux)."""

    def __init__(self, padre, texto, comando, color="primario", **kw):
        base = COLORES.get(color, color)
        super().__init__(padre, text=texto, bg=base, fg="white", font=FUENTE_B, padx=14, pady=6, cursor="hand2", **kw)
        self._base, self._hover, self._cmd = base, oscurecer(base), comando
        self.bind("<Enter>", lambda e: self.configure(bg=self._hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self._base))
        self.bind("<Button-1>", lambda e: self._cmd())

    def pintar(self, color):
        self._base = COLORES.get(color, color)
        self._hover = oscurecer(self._base)
        self.configure(bg=self._base)


def boton(padre, texto, comando, color="primario", lado="left"):
    b = Boton(padre, texto, comando, color)
    b.pack(side=lado, padx=(0, 8) if lado == "left" else (8, 0), pady=4)
    return b


def entrada(padre, ancho=30, mostrar=""):
    return tk.Entry(padre, width=ancho, font=FUENTE, relief="flat", bg=BLANCO, fg=TEXTO, show=mostrar,
                    highlightthickness=1, highlightbackground="#d1d5db", highlightcolor=COLORES["primario"],
                    insertbackground=TEXTO)


def crear_tabla(padre, columnas, anchos, alto=12, izq=()):
    marco = tk.Frame(padre, bg=BLANCO, highlightthickness=1, highlightbackground=BORDE)
    marco.pack(fill="both", expand=True, pady=(0, 8))
    tree = ttk.Treeview(marco, columns=columnas, show="headings", height=alto, style="Tabla.Treeview")
    sb = ttk.Scrollbar(marco, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    for col, ancho in zip(columnas, anchos):
        ancla = "w" if col in izq else "center"
        tree.heading(col, text=col, anchor=ancla)
        tree.column(col, width=ancho, minwidth=40, anchor=ancla)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    tree.tag_configure("par", background=BLANCO)
    tree.tag_configure("impar", background="#f9fafb")
    for tipo, color in ALERTAS_COLOR.items():
        tree.tag_configure(tag_de(tipo), background=color)
    return tree


def llenar(tree, filas, tags=None):
    tree.delete(*tree.get_children())
    for i, fila in enumerate(filas):
        tag = (tags[i] if tags and tags[i] else ("par" if i % 2 == 0 else "impar"))
        tree.insert("", "end", values=fila, tags=(tag,))


def seleccionado(tree, mensaje="Selecciona una fila de la tabla."):
    sel = tree.selection()
    if not sel:
        messagebox.showwarning("Selección", mensaje)
        return None
    return int(tree.item(sel[0])["values"][0])


def tarjetas(padre, datos, por_fila=3):
    marco = tk.Frame(padre, bg=FONDO)
    marco.pack(fill="x", pady=(0, 8))
    for i, d in enumerate(datos):
        fila, col = divmod(i, por_fila)
        card = tk.Frame(marco, bg=BLANCO, highlightthickness=1, highlightbackground=BORDE, padx=16, pady=10)
        card.grid(row=fila, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0), pady=4)
        marco.grid_columnconfigure(col, weight=1, uniform="k")
        tk.Label(card, text=d["titulo"], bg=BLANCO, fg=GRIS, font=("Segoe UI", 9), anchor="w").pack(fill="x")
        tk.Label(card, text=d["valor"], bg=BLANCO, fg=NIVELES.get(d.get("nivel", "info"), TEXTO),
                 font=("Segoe UI", 17, "bold"), anchor="w").pack(fill="x")


class Formulario(tk.Toplevel):
    """Ventana modal genérica. campos = [(clave, etiqueta, valor_inicial, opcion)]
    donde opcion puede ser None, '*' (contraseña) o una lista (lista desplegable)."""

    def __init__(self, padre, titulo, campos, al_guardar, texto_boton="Guardar"):
        super().__init__(padre)
        self.title(titulo)
        self.configure(bg=BLANCO, padx=24, pady=18)
        self.resizable(False, False)
        self.transient(padre)
        self.grab_set()
        tk.Label(self, text=titulo, font=("Segoe UI", 14, "bold"), bg=BLANCO, fg=TEXTO).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.widgets = {}
        for i, (clave, etiqueta, inicial, opcion) in enumerate(campos, start=1):
            tk.Label(self, text=etiqueta, bg=BLANCO, fg=GRIS, font=FUENTE, anchor="w").grid(
                row=i, column=0, sticky="w", padx=(0, 14), pady=5)
            if isinstance(opcion, (list, tuple)):
                w = ttk.Combobox(self, values=opcion, state="readonly", width=28)
                w.set(inicial)
            else:
                w = entrada(self, 31, "*" if opcion == "*" else "")
                w.insert(0, inicial)
            w.grid(row=i, column=1, pady=5)
            self.widgets[clave] = w
        self.al_guardar = al_guardar
        Boton(self, texto_boton, self.guardar, "exito").grid(row=len(campos) + 1, column=0, columnspan=2,
                                                              sticky="e", pady=(14, 0))

    def guardar(self):
        valores = {k: w.get().strip() for k, w in self.widgets.items()}
        try:
            self.al_guardar(valores)
        except db.ErrorNegocio as e:
            messagebox.showerror("Revisa los datos", str(e), parent=self)
            return
        self.destroy()


# ------------------------------------------------------------ aplicación
class App:
    def __init__(self, root):
        self.root = root
        root.title("SysMayor — Inventario y pedidos para distribuidoras mayoristas")
        root.geometry("1240x720")
        root.minsize(1100, 660)
        self.configurar_estilos()
        db.init_db()
        try:
            db.respaldar()
        except Exception:
            pass
        root.protocol("WM_DELETE_WINDOW", self.cerrar)
        root.report_callback_exception = self.error_inesperado
        self.usuario, self.carrito, self.items, self.vistas, self.activo = None, [], {}, {}, None
        self.mostrar_login()

    def configurar_estilos(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("Tabla.Treeview", background=BLANCO, fieldbackground=BLANCO, foreground=TEXTO,
                    rowheight=28, borderwidth=0, font=FUENTE)
        s.configure("Tabla.Treeview.Heading", background="#1f2937", foreground="white", font=FUENTE_B,
                    relief="flat", padding=(6, 7))
        s.map("Tabla.Treeview", background=[("selected", "#bfdbfe")], foreground=[("selected", TEXTO)])
        s.map("Tabla.Treeview.Heading", background=[("active", "#374151")])
        s.configure("TNotebook", background=FONDO, borderwidth=0)
        s.configure("TNotebook.Tab", padding=(16, 8), font=FUENTE_B, background="#e5e7eb")
        s.map("TNotebook.Tab", background=[("selected", BLANCO)])

    def error_inesperado(self, tipo, valor, _traza):
        """Muestra un mensaje entendible cuando la base está ocupada o tiene datos mal escritos a mano."""
        if issubclass(tipo, sqlite3.OperationalError) and "locked" in str(valor):
            messagebox.showwarning("Base de datos en uso",
                                   "Otro programa (DBeaver, DB Browser) tiene cambios sin guardar en la base.\n\n"
                                   "Guarda los cambios (Commit / Write Changes) o cierra esa conexión y vuelve a intentarlo.")
        else:
            messagebox.showerror("Algo salió mal",
                                 f"{tipo.__name__}: {valor}\n\nSi acabas de editar la base de datos a mano, revisa que "
                                 "las fechas sean AAAA-MM-DD y que cantidades y precios sean solo números.")

    def cerrar(self):
        try:
            db.respaldar()
        except Exception:
            pass
        self.root.destroy()

    def limpiar(self):
        for w in self.root.winfo_children():
            w.destroy()

    def ejecutar(self, accion, despues=None, exito=None):
        """Ejecuta una acción mostrando los errores de negocio. Devuelve (ok, resultado)."""
        try:
            res = accion()
        except db.ErrorNegocio as e:
            messagebox.showerror("No se pudo completar", str(e))
            return False, None
        if exito:
            messagebox.showinfo("Listo", exito)
        if despues:
            despues()
        self.actualizar_insignias()
        return True, res

    def nueva_vista(self, titulo, subtitulo=""):
        for w in self.contenido.winfo_children():
            w.destroy()
        tk.Label(self.contenido, text=titulo, font=TITULO, bg=FONDO, fg=TEXTO, anchor="w").pack(fill="x")
        tk.Label(self.contenido, text=subtitulo, font=SUBTITULO, bg=FONDO, fg=GRIS, anchor="w").pack(
            fill="x", pady=(0, 12))
        return self.contenido

    def exportar(self, nombre, columnas, filas):
        ruta = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=f"{nombre}.csv",
                                            filetypes=[("CSV (Excel)", "*.csv")])
        if ruta:
            db.exportar_csv(ruta, columnas, filas)
            messagebox.showinfo("Exportado", f"Archivo guardado en:\n{ruta}")

    # ----------------------------------------------------------------- login
    def mostrar_login(self):
        self.limpiar()
        self.usuario, self.carrito = None, []
        izq = tk.Frame(self.root, bg=LATERAL, width=460)
        izq.pack(side="left", fill="y")
        izq.pack_propagate(False)
        tk.Label(izq, text="📦", font=("Segoe UI Emoji", 54), bg=LATERAL, fg="white").pack(pady=(170, 0))
        tk.Label(izq, text="SysMayor", font=("Segoe UI", 30, "bold"), bg=LATERAL, fg="white").pack()
        tk.Label(izq, text="Inventario y pedidos para\ndistribuidoras mayoristas", font=("Segoe UI", 12),
                 bg=LATERAL, fg="#9ca3af", justify="center").pack(pady=(6, 0))
        tk.Label(izq, text="Soledad · Barranquilla", font=("Segoe UI", 10), bg=LATERAL, fg="#6b7280").pack(pady=(26, 0))

        der = tk.Frame(self.root, bg=BLANCO)
        der.pack(side="left", fill="both", expand=True)
        form = tk.Frame(der, bg=BLANCO)
        form.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(form, text="Bienvenido", font=("Segoe UI", 22, "bold"), bg=BLANCO, fg=TEXTO).pack(anchor="w")
        tk.Label(form, text="Inicia sesión para continuar", font=FUENTE, bg=BLANCO, fg=GRIS).pack(anchor="w", pady=(0, 22))
        tk.Label(form, text="Usuario", font=FUENTE_B, bg=BLANCO, fg=TEXTO).pack(anchor="w")
        e_user = entrada(form, 34)
        e_user.pack(fill="x", ipady=6, pady=(4, 14))
        tk.Label(form, text="Contraseña", font=FUENTE_B, bg=BLANCO, fg=TEXTO).pack(anchor="w")
        e_clave = entrada(form, 34, "*")
        e_clave.pack(fill="x", ipady=6, pady=(4, 20))

        def entrar(_=None):
            if not e_user.get().strip() or not e_clave.get():
                messagebox.showwarning("Campos vacíos", "Completa usuario y contraseña.")
                return
            u = db.autenticar(e_user.get(), e_clave.get())
            if not u:
                messagebox.showerror("Error", "Usuario o contraseña incorrectos.")
                e_clave.delete(0, tk.END)
                return
            self.mostrar_principal(u)

        Boton(form, "Iniciar sesión", entrar, "primario").pack(fill="x")
        e_user.bind("<Return>", entrar)
        e_clave.bind("<Return>", entrar)
        e_user.focus()

    # ------------------------------------------------------------- principal
    def opciones_menu(self):
        """Lista de ('seccion', título) y (clave, texto, función) según el rol."""
        rol = self.usuario["rol"]
        inicio = ("inicio", "🏠  Inicio", self.vista_inicio)
        mayorista = [("inventario", "📦  Inventario", self.vista_inventario),
                     ("registro", "➕  Registrar producto", self.vista_registro),
                     ("recibidos", "📋  Pedidos recibidos", lambda: self.vista_pedidos("recibidos")),
                     ("alertas", "⚠️  Alertas", lambda: self.vista_alertas("mayorista")),
                     ("reportes", "📊  Reportes", self.vista_reportes),
                     ("ganancias", "💰  Ganancias", lambda: self.vista_ganancias("mayorista"))]
        pedir = ("pedir", "🛒  Pedir al mayorista", self.vista_pedir_mayorista)
        tienda = [("mi_inv", "🏪  Mi inventario", self.vista_mi_inventario),
                  ("ventas", "🛍️  Ventas a compradores", lambda: self.vista_pedidos("ventas")),
                  ("alertas_t", "⚠️  Alertas de mi tienda", lambda: self.vista_alertas("tienda")),
                  ("ganancias_t", "💰  Mis ganancias", lambda: self.vista_ganancias("tienda"))]
        comprar = ("comprar", "🛒  Comprar en una tienda", self.vista_comprar_tienda)
        mis = ("mis_pedidos", "🧾  Mis pedidos", lambda: self.vista_pedidos("compras"))
        if rol == "Vendedor":
            return [inicio] + mayorista
        if rol == "Tendero":
            return [inicio, pedir, mis] + tienda
        if rol == "Comprador":
            return [inicio, comprar, mis]
        return ([inicio, ("sec", "MAYORISTA")] + mayorista + [("sec", "MI TIENDA (TENDERO)"), pedir] + tienda +
                [("sec", "COMPRAS (COMPRADOR)"), comprar, mis, ("sec", "SISTEMA"),
                 ("admin", "👥  Administración", self.vista_admin)])

    def mostrar_principal(self, usuario):
        self.limpiar()
        self.usuario, self.carrito, self.items, self.vistas = usuario, [], {}, {}
        opciones = self.opciones_menu()
        pady = 3 if len(opciones) > 12 else 6

        lat = tk.Frame(self.root, bg=LATERAL, width=250)
        lat.pack(side="left", fill="y")
        lat.pack_propagate(False)
        tk.Label(lat, text="📦 SysMayor", font=("Segoe UI", 16, "bold"), bg=LATERAL, fg="white").pack(anchor="w", padx=20, pady=(18, 2))
        tk.Label(lat, text=f"{usuario['usuario']} · {usuario['rol']}", font=("Segoe UI", 9), bg=LATERAL, fg="#9ca3af").pack(anchor="w", padx=20)
        tk.Label(lat, text=usuario["tienda"], font=("Segoe UI", 9), bg=LATERAL, fg="#6b7280").pack(anchor="w", padx=20, pady=(0, 10))
        menu = tk.Frame(lat, bg=LATERAL)
        menu.pack(fill="x")
        for op in opciones:
            if op[0] == "sec":
                tk.Label(menu, text=op[1], font=("Segoe UI", 8, "bold"), bg=LATERAL, fg="#6b7280", anchor="w").pack(
                    fill="x", padx=20, pady=(10, 2))
                continue
            clave, texto, fn = op
            lbl = tk.Label(menu, text=texto, bg=LATERAL, fg="#d1d5db", font=FUENTE, anchor="w", padx=20, pady=pady, cursor="hand2")
            lbl.pack(fill="x")
            lbl.bind("<Enter>", lambda e, w=lbl, k=clave: w.configure(bg=LATERAL_ACTIVO if self.activo == k else LATERAL_HOVER))
            lbl.bind("<Leave>", lambda e, w=lbl, k=clave: w.configure(bg=LATERAL_ACTIVO if self.activo == k else LATERAL))
            lbl.bind("<Button-1>", lambda e, k=clave: self.ir(k))
            self.items[clave], self.vistas[clave] = (lbl, texto), fn
        salir = tk.Label(lat, text="⏻  Cerrar sesión", bg=LATERAL, fg="#fca5a5", font=FUENTE_B, anchor="w",
                         padx=20, pady=10, cursor="hand2")
        salir.pack(side="bottom", fill="x")
        salir.bind("<Button-1>", lambda e: self.mostrar_login())
        salir.bind("<Enter>", lambda e: salir.configure(bg=LATERAL_HOVER))
        salir.bind("<Leave>", lambda e: salir.configure(bg=LATERAL))

        self.contenido = tk.Frame(self.root, bg=FONDO, padx=26, pady=20)
        self.contenido.pack(side="left", fill="both", expand=True)
        self.actualizar_insignias()
        self.ir("inicio")

    def ir(self, clave):
        self.activo = clave
        for k, (lbl, _) in self.items.items():
            lbl.configure(bg=LATERAL_ACTIVO if k == clave else LATERAL, fg="white" if k == clave else "#d1d5db")
        self.vistas[clave]()

    def actualizar_insignias(self):
        """Muestra entre paréntesis cuántas alertas o pedidos pendientes hay en cada opción del menú."""
        u, datos = self.usuario, {}
        try:
            if "alertas" in self.items:
                datos["alertas"] = sum(db.resumen_alertas().values())
            if "alertas_t" in self.items:
                datos["alertas_t"] = len(db.alertas_tienda(u))
            if "recibidos" in self.items:
                datos["recibidos"] = len(db.listar_pedidos(u, ["PENDIENTE"]))
            if "ventas" in self.items:
                datos["ventas"] = len(db.listar_pedidos(u, ["PENDIENTE"], "ventas"))
        except Exception:
            return
        for clave, n in datos.items():
            lbl, base = self.items[clave]
            lbl.configure(text=f"{base}   ({n})" if n else base)

    # ---------------------------------------------------------------- inicio
    def vista_inicio(self):
        u = self.usuario
        c = self.nueva_vista(f"Hola, {u['usuario']} 👋", f"{u['rol']} · {u['tienda']} — {u['direccion']}")
        tarjetas(c, db.panel(u))
        if u["rol"] in db.ROLES_MAYORISTA:
            lista = db.alertas()
        elif u["rol"] == "Tendero":
            lista = db.alertas_tienda(u)
        else:
            tk.Label(c, text="Entra a «Comprar en una tienda» para ver qué productos tiene cada tendero.",
                     font=FUENTE, bg=FONDO, fg=GRIS).pack(anchor="w", pady=10)
            return
        if not lista:
            tk.Label(c, text="✅ Todo en orden: no hay alertas de inventario.", font=FUENTE_B, bg=FONDO,
                     fg=COLORES["exito"]).pack(anchor="w", pady=10)
            return
        tk.Label(c, text=f"⚠️ Atención requerida ({len(lista)})", font=("Segoe UI", 12, "bold"), bg=FONDO,
                 fg=TEXTO).pack(anchor="w", pady=(6, 4))
        tree = crear_tabla(c, ("Alerta", "Producto", "Lote", "Stock", "Vence", "Días"), (120, 270, 100, 70, 110, 160), 7,
                           izq=("Producto",))
        llenar(tree, [(a["tipo"], a["nombre"], a["lote"], a["cantidad"], a["vencimiento"], texto_dias(a["dias"]))
                      for a in lista[:12]], [tag_de(a["tipo"]) for a in lista[:12]])

    # ----------------------------------------------- mayorista: inventario
    def vista_inventario(self):
        c = self.nueva_vista("📦 Inventario del mayorista", "Productos en bodega por lote, con costo, precios y vencimiento")
        barra = tk.Frame(c, bg=FONDO)
        barra.pack(fill="x", pady=(0, 8))
        tk.Label(barra, text="Buscar:", bg=FONDO, font=FUENTE_B).pack(side="left")
        buscar = tk.StringVar()
        e = entrada(barra, 34)
        e.configure(textvariable=buscar)
        e.pack(side="left", padx=8, ipady=3)
        cols = ("ID", "Producto", "Lote", "Stock", "Mínimo", "Costo", "P. mayorista", "P. sugerido", "Vence", "Estado")
        tree = crear_tabla(c, cols, (45, 200, 80, 60, 65, 85, 100, 100, 95, 150), 14, izq=("Producto",))
        dias_alerta = int(db.get_config("dias_alerta_vencimiento", 7))

        def cargar(*_):
            filas, tags = [], []
            for p in db.listar_productos(buscar.get().strip()):
                est, _d = db.estados_producto(p, dias_alerta)
                sin_precio = ["SIN PRECIO"] if p["precio_mayorista"] <= 0 else []
                filas.append((p["id"], p["nombre"], p["lote"], p["cantidad"], p["stock_minimo"],
                              db.dinero(p["precio_costo"]), db.dinero(p["precio_mayorista"]),
                              db.dinero(p["precio_sugerido"]), p["fecha_vencimiento"], ", ".join(est + sin_precio) or "OK"))
                tags.append(tag_de(est[0]) if est else None)
            llenar(tree, filas, tags)

        buscar.trace_add("write", cargar)

        def reponer():
            pid = seleccionado(tree)
            if pid is None:
                return
            n = simpledialog.askinteger("Reponer stock", "Unidades que ingresan a bodega:", parent=self.root, minvalue=1)
            if n:
                self.ejecutar(lambda: db.reponer_stock(pid, n, self.usuario["usuario"]), cargar, "Stock actualizado.")

        def editar():
            pid = seleccionado(tree)
            if pid is None:
                return
            p = db.obtener_producto(pid)

            def guardar(v):
                db.editar_producto(pid, v["min"], v["costo"], v["pm"], v["ps"], v["venc"], self.usuario["usuario"])
                cargar()
                self.actualizar_insignias()

            Formulario(self.root, f"Editar: {p['nombre']} (lote {p['lote']})", [
                ("min", "Stock mínimo:", p["stock_minimo"], None),
                ("costo", "Costo de compra ($):", int(p["precio_costo"]), None),
                ("pm", "Precio mayorista ($):", int(p["precio_mayorista"]), None),
                ("ps", "Precio sugerido ($):", int(p["precio_sugerido"]), None),
                ("venc", "Vencimiento (AAAA-MM-DD):", p["fecha_vencimiento"], None)], guardar)

        def retirar():
            pid = seleccionado(tree)
            if pid is None:
                return
            p = db.obtener_producto(pid)
            if not messagebox.askyesno("Retirar lote vencido",
                                       f"Se retirará «{p['nombre']}» (lote {p['lote']}) del inventario y se registrará "
                                       f"una pérdida de {db.dinero(p['cantidad'] * p['precio_costo'])} "
                                       f"({p['cantidad']} unidades a costo).\n\n¿Continuar?"):
                return
            ok, perdida = self.ejecutar(lambda: db.retirar_vencido(pid, self.usuario["usuario"]), cargar)
            if ok:
                messagebox.showinfo("Pérdida registrada", f"Pérdida por vencimiento: {db.dinero(perdida)}.")

        def eliminar():
            pid = seleccionado(tree)
            if pid is None:
                return
            if messagebox.askyesno("Eliminar producto",
                                   "Se borrará el producto de la base de datos (no se registra como pérdida).\n"
                                   "El historial de pedidos y movimientos se conserva.\n\n¿Eliminar definitivamente?"):
                self.ejecutar(lambda: db.eliminar_producto(pid, self.usuario["usuario"]), cargar)

        acc = tk.Frame(c, bg=FONDO)
        acc.pack(fill="x")
        boton(acc, "➕ Reponer stock", reponer, "exito")
        boton(acc, "✏️ Editar", editar, "primario")
        boton(acc, "⏳ Retirar vencido (pérdida)", retirar, "aviso")
        boton(acc, "🗑️ Eliminar", eliminar, "peligro", "right")
        cargar()

    def vista_registro(self):
        c = self.nueva_vista("➕ Registrar producto", "Ingresa un nuevo lote a la bodega del mayorista")
        card = tk.Frame(c, bg=BLANCO, highlightthickness=1, highlightbackground=BORDE, padx=26, pady=20)
        card.pack(anchor="w")
        campos = [("nombre", "Nombre del producto", ""), ("lote", "Número de lote", ""),
                  ("cant", "Cantidad que ingresa", ""), ("min", "Stock mínimo (alerta)", db.get_config("stock_minimo_defecto", 10)),
                  ("costo", "Costo de compra al proveedor ($)", ""), ("pm", "Precio mayorista ($)", ""),
                  ("ps", "Precio sugerido al público ($)", ""), ("venc", "Vencimiento (AAAA-MM-DD)", "")]
        ents = {}
        for i, (k, etiqueta, inicial) in enumerate(campos):
            fila, col = divmod(i, 2)
            px = (0, 0) if col == 0 else (28, 0)
            tk.Label(card, text=etiqueta, bg=BLANCO, fg=GRIS, font=("Segoe UI", 9), anchor="w").grid(
                row=fila * 2, column=col, sticky="w", padx=px, pady=(10, 2))
            e = entrada(card, 32)
            e.insert(0, inicial)
            e.grid(row=fila * 2 + 1, column=col, sticky="w", padx=px, ipady=4)
            ents[k] = e

        def guardar():
            v = {k: e.get() for k, e in ents.items()}
            ok, _ = self.ejecutar(lambda: db.registrar_producto(
                v["nombre"], v["lote"], v["cant"], v["min"], v["costo"], v["pm"], v["ps"], v["venc"],
                self.usuario["usuario"]), exito="Producto registrado en el inventario.")
            if ok:
                for k in ("nombre", "lote", "cant", "costo", "pm", "ps", "venc"):
                    ents[k].delete(0, tk.END)

        tk.Label(c, text="Ganancia del mayorista por unidad = precio mayorista − costo de compra.",
                 font=("Segoe UI", 9), bg=FONDO, fg=GRIS).pack(anchor="w", pady=(10, 6))
        Boton(c, "💾 Guardar en inventario", guardar, "exito").pack(anchor="w")

    # --------------------------------------------------------------- pedidos
    def vista_pedidos(self, modo):
        u = self.usuario
        admin = u["rol"] == "Administrador"
        info = {"recibidos": ("📋 Pedidos recibidos", "Pedidos de los tenderos al mayorista" +
                              (" y compras en tiendas (vista de administrador)" if admin else "")),
                "compras": ("🧾 Mis pedidos", "Lo que has pedido al mayorista o comprado en tiendas"),
                "ventas": ("🛍️ Ventas a compradores", "Pedidos que los compradores le hacen a tu tienda")}
        c = self.nueva_vista(*info[modo])
        como = {"recibidos": None, "compras": "compras", "ventas": "ventas"}[modo]
        vista = {"historial": False}

        barra = tk.Frame(c, bg=FONDO)
        barra.pack(fill="x", pady=(0, 8))
        b1 = Boton(barra, "En curso", lambda: poner(False), "primario")
        b1.pack(side="left", padx=(0, 4))
        b2 = Boton(barra, "Historial", lambda: poner(True), "neutro")
        b2.pack(side="left")

        cols = ("ID", "Fecha", "Comprador", "Entrega en", "Vendedor", "Productos", "Total", "Estado")
        tree = crear_tabla(c, cols, (45, 125, 95, 170, 130, 250, 85, 100), 11, izq=("Entrega en", "Vendedor", "Productos"))

        def cargar():
            estados = db.ESTADOS_FINALES if vista["historial"] else db.ESTADOS_ACTIVOS
            llenar(tree, [(p["id"], p["fecha_creacion"][:16], p["usuario"], p["direccion"], p["vendedor"],
                           p["resumen"], db.dinero(p["total"]), p["estado"])
                          for p in db.listar_pedidos(u, estados, como)])

        def poner(historial):
            vista["historial"] = historial
            b1.pintar("neutro" if historial else "primario")
            b2.pintar("primario" if historial else "neutro")
            if historial:
                cambios.pack_forget()
            else:
                cambios.pack(side="left")
            cargar()

        def cambiar(nuevo, verbo):
            pid = seleccionado(tree, "Selecciona un pedido de la tabla.")
            if pid is None:
                return
            detalle = ""
            if nuevo == "RECHAZADO":
                detalle = simpledialog.askstring("Rechazar pedido", "Motivo (opcional):", parent=self.root)
                if detalle is None:
                    return
            elif not messagebox.askyesno("Confirmar", f"¿{verbo} el pedido #{pid}?"):
                return
            self.ejecutar(lambda: db.cambiar_estado(pid, nuevo, u, detalle), cargar, f"Pedido #{pid}: {nuevo}.")

        def ver():
            pid = seleccionado(tree, "Selecciona un pedido de la tabla.")
            if pid is not None:
                self.detalle_pedido(pid)

        vendedor_b = [("✅ Aprobar", "APROBADO", "Aprobar", "exito"), ("❌ Rechazar", "RECHAZADO", "Rechazar", "peligro"),
                      ("🚚 Despachar", "DESPACHADO", "Marcar como despachado", "info")]
        comprador_b = [("📥 Confirmar recepción", "ENTREGADO", "Confirmar la recepción de", "info"),
                       ("🚫 Cancelar", "CANCELADO", "Cancelar", "peligro")]
        cliente_b = [("📦 Entregado al cliente", "ENTREGADO", "Marcar como entregado", "info")]
        lista = {"recibidos": vendedor_b + (comprador_b if admin else []),
                 "compras": comprador_b, "ventas": vendedor_b + cliente_b}[modo]

        acc = tk.Frame(c, bg=FONDO)
        acc.pack(fill="x")
        cambios = tk.Frame(acc, bg=FONDO)
        cambios.pack(side="left")
        for texto, nuevo, verbo, color in lista:
            boton(cambios, texto, lambda n=nuevo, v=verbo: cambiar(n, v), color)
        boton(acc, "🔎 Ver detalle", ver, "neutro", "right")
        tree.bind("<Double-1>", lambda _e: ver())
        cargar()

    def detalle_pedido(self, pedido_id):
        p = db.obtener_pedido(pedido_id)
        if not p:
            return
        win = tk.Toplevel(self.root)
        win.title(f"Pedido #{pedido_id}")
        win.configure(bg=FONDO)
        win.geometry("800x600")
        tk.Label(win, text=f"Pedido #{pedido_id} · {p['estado']}", font=("Segoe UI", 16, "bold"), bg=FONDO,
                 fg=TEXTO, anchor="w").pack(fill="x", padx=20, pady=(18, 0))
        tk.Label(win, text=f"Comprador: {p['usuario']} ({p['tienda']})   ·   Vendedor: {p['vendedor']}   ·   "
                           f"Total: {db.dinero(p['total'])}", font=FUENTE, bg=FONDO, fg=GRIS, anchor="w").pack(fill="x", padx=20)
        cont = tk.Frame(win, bg=FONDO)
        cont.pack(fill="both", expand=True, padx=20, pady=12)
        tk.Label(cont, text="Productos", font=FUENTE_B, bg=FONDO).pack(anchor="w", pady=(0, 3))
        t1 = crear_tabla(cont, ("Producto", "Lote", "Vence", "Cant.", "P. unitario", "Subtotal", "Venta al público"),
                         (200, 80, 95, 55, 95, 95, 120), 5, izq=("Producto",))
        llenar(t1, [(i["nombre_producto"], i["lote"], i["fecha_vencimiento"], i["cantidad"], db.dinero(i["precio_unitario"]),
                     db.dinero(i["cantidad"] * i["precio_unitario"]), db.dinero(i["precio_publico"]))
                    for i in db.items_pedido(pedido_id)])
        tk.Label(cont, text="Seguimiento", font=FUENTE_B, bg=FONDO).pack(anchor="w", pady=(8, 3))
        t2 = crear_tabla(cont, ("Fecha", "Estado", "Usuario", "Detalle"), (150, 110, 110, 300), 5, izq=("Detalle",))
        llenar(t2, [(h["fecha"], h["estado"], h["usuario"], h["detalle"]) for h in db.historial_pedido(pedido_id)])

    # ------------------------------------------------ pedir / comprar (carrito)
    def vista_pedir_mayorista(self):
        self._vista_carrito("mayorista")

    def vista_comprar_tienda(self):
        self._vista_carrito("tienda")

    def _vista_carrito(self, origen):
        u = self.usuario
        mayorista = origen == "mayorista"
        c = self.nueva_vista("🛒 Pedir al mayorista" if mayorista else "🛒 Comprar en una tienda",
                             ("Elige productos y cantidades" if mayorista else "Compra directamente a un tendero")
                             + f" · entrega en {u['direccion']}")
        self.carrito = []
        estado = {"tienda": None, "catalogo": {}}

        if not mayorista:
            tiendas = [t for t in db.listar_tiendas() if t["id"] != u["id"]]
            fila = tk.Frame(c, bg=FONDO)
            fila.pack(fill="x", pady=(0, 8))
            tk.Label(fila, text="Tienda:", bg=FONDO, font=FUENTE_B).pack(side="left")
            combo = ttk.Combobox(fila, state="readonly", width=66,
                                 values=[f"{t['nombre_tienda']} — {t['direccion']}  ({t['productos']} productos)" for t in tiendas])
            combo.pack(side="left", padx=8)
            if not tiendas:
                tk.Label(fila, text="Aún no hay tiendas registradas.", bg=FONDO, fg=GRIS, font=FUENTE).pack(side="left")

        if mayorista:
            cols, anchos = ("ID", "Producto", "Lote", "Disponible", "P. mayorista", "P. sugerido", "Vence"), (45, 230, 90, 85, 105, 105, 100)
        else:
            cols, anchos = ("ID", "Producto", "Lote", "Disponible", "Precio", "Vence"), (45, 260, 100, 90, 110, 110)
        cat = crear_tabla(c, cols, anchos, 6, izq=("Producto",))

        def cargar_catalogo():
            if mayorista:
                filas = [{"id": p["id"], "nombre": p["nombre"], "lote": p["lote"], "cant": p["cantidad"],
                          "precio": p["precio_mayorista"], "sug": p["precio_sugerido"], "venc": p["fecha_vencimiento"]}
                         for p in db.listar_productos(solo_disponibles=True)]
            elif estado["tienda"]:
                filas = [{"id": p["id"], "nombre": p["nombre_producto"], "lote": p["lote"], "cant": p["cantidad"],
                          "precio": p["precio_venta"], "sug": p["precio_venta"], "venc": p["fecha_vencimiento"]}
                         for p in db.catalogo_tienda(estado["tienda"])]
            else:
                filas = []
            estado["catalogo"] = {f["id"]: f for f in filas}
            if mayorista:
                llenar(cat, [(f["id"], f["nombre"], f["lote"], f["cant"], db.dinero(f["precio"]), db.dinero(f["sug"]), f["venc"]) for f in filas])
            else:
                llenar(cat, [(f["id"], f["nombre"], f["lote"], f["cant"], db.dinero(f["precio"]), f["venc"]) for f in filas])

        fila = tk.Frame(c, bg=FONDO)
        fila.pack(fill="x", pady=(2, 4))
        tk.Label(fila, text="Cantidad:", bg=FONDO, font=FUENTE_B).pack(side="left")
        e_cant = entrada(fila, 8)
        e_cant.pack(side="left", padx=(6, 18), ipady=3)
        e_pub = None
        if mayorista:
            tk.Label(fila, text="Tu precio de venta al público ($):", bg=FONDO, font=FUENTE_B).pack(side="left")
            e_pub = entrada(fila, 10)
            e_pub.pack(side="left", padx=6, ipady=3)

        def al_elegir_producto(_=None):
            sel = cat.selection()
            if sel and e_pub is not None:
                f = estado["catalogo"].get(int(cat.item(sel[0])["values"][0]))
                if f:
                    e_pub.delete(0, tk.END)
                    e_pub.insert(0, int(f["sug"]))

        cat.bind("<<TreeviewSelect>>", al_elegir_producto)

        tk.Label(c, text="🧺 Tu pedido", font=("Segoe UI", 12, "bold"), bg=FONDO, fg=TEXTO).pack(anchor="w", pady=(8, 2))
        cols_c = ("ID", "Producto", "Lote", "Cant.", "Precio unit.", "Subtotal") + (("Tu precio al público",) if mayorista else ())
        carro = crear_tabla(c, cols_c, (45, 230, 90, 60, 105, 105, 140)[:len(cols_c)], 4, izq=("Producto",))
        acc = tk.Frame(c, bg=FONDO)
        acc.pack(fill="x")

        def refrescar():
            filas = []
            for i in self.carrito:
                f = (i["id"], i["nombre"], i["lote"], i["cant"], db.dinero(i["precio"]), db.dinero(i["cant"] * i["precio"]))
                filas.append(f + ((db.dinero(i["pub"]),) if mayorista else ()))
            llenar(carro, filas)
            lbl_total.config(text=f"Total: {db.dinero(sum(i['cant'] * i['precio'] for i in self.carrito))}")

        if not mayorista:
            def al_elegir_tienda(_=None):
                idx = combo.current()
                if idx < 0:
                    return
                nueva = tiendas[idx]["id"]
                if self.carrito and nueva != estado["tienda"]:
                    if not messagebox.askyesno("Cambiar de tienda", "Al cambiar de tienda se vacía tu pedido actual. ¿Continuar?"):
                        combo.current([t["id"] for t in tiendas].index(estado["tienda"]))
                        return
                    self.carrito.clear()
                    refrescar()
                estado["tienda"] = nueva
                cargar_catalogo()

            combo.bind("<<ComboboxSelected>>", al_elegir_tienda)

        def agregar():
            pid = seleccionado(cat, "Selecciona un producto del catálogo.")
            if pid is None:
                return
            f = estado["catalogo"].get(pid)
            if not f:
                return
            try:
                cant = db.validar_entero(e_cant.get(), "La cantidad", 1)
                pub = db.validar_numero(e_pub.get(), "El precio al público") if mayorista else f["precio"]
            except db.ErrorNegocio as e:
                messagebox.showerror("Revisa los datos", str(e))
                return
            ya = sum(i["cant"] for i in self.carrito if i["id"] == pid)
            if ya + cant > f["cant"]:
                messagebox.showerror("Stock", f"Solo hay {f['cant']} unidades disponibles (ya tienes {ya} en el pedido).")
                return
            for i in self.carrito:
                if i["id"] == pid:
                    i["cant"] += cant
                    i["pub"] = pub
                    break
            else:
                self.carrito.append({"id": pid, "nombre": f["nombre"], "lote": f["lote"], "cant": cant,
                                     "precio": f["precio"], "pub": pub})
            e_cant.delete(0, tk.END)
            refrescar()

        def quitar():
            pid = seleccionado(carro, "Selecciona un producto del pedido para quitarlo.")
            if pid is not None:
                self.carrito = [i for i in self.carrito if i["id"] != pid]
                refrescar()

        def enviar():
            if not self.carrito:
                messagebox.showwarning("Pedido vacío", "Agrega al menos un producto.")
                return
            if not messagebox.askyesno("Confirmar", "¿Enviar el pedido?"):
                return
            items = ([(i["id"], i["cant"], i["pub"]) for i in self.carrito] if mayorista
                     else [(i["id"], i["cant"]) for i in self.carrito])
            ok, pedido_id = self.ejecutar(lambda: db.crear_pedido(u, items, tienda_id=None if mayorista else estado["tienda"]))
            if ok:
                self.carrito = []
                messagebox.showinfo("Pedido enviado", f"Pedido #{pedido_id} enviado.\nQueda PENDIENTE hasta que "
                                    f"{'el mayorista' if mayorista else 'la tienda'} lo apruebe.")
                self._vista_carrito(origen)

        boton(acc, "➕ Agregar al pedido", agregar, "exito")
        boton(acc, "➖ Quitar", quitar, "neutro")
        boton(acc, "📨 Enviar pedido", enviar, "primario", "right")
        lbl_total = tk.Label(acc, text="", font=("Segoe UI", 12, "bold"), bg=FONDO, fg=TEXTO)
        lbl_total.pack(side="right", padx=14)
        cargar_catalogo()
        refrescar()

    # ------------------------------------------------- tendero: mi inventario
    def vista_mi_inventario(self):
        u = self.usuario
        c = self.nueva_vista("🏪 Mi inventario", f"{u['tienda']} · lo que compraste al mayorista, con lote, vencimiento y ganancia")
        dias = int(db.get_config("dias_alerta_vencimiento", 7))
        filas_db = db.inventario_tienda(u)
        costo = sum(i["cantidad"] * i["costo_unitario"] for i in filas_db)
        potencial = sum(i["cantidad"] * (i["precio_venta"] - i["costo_unitario"]) for i in filas_db
                        if "VENCIDO" not in db.estados_producto(i, dias)[0])
        n_alerta = sum(1 for i in filas_db if set(db.estados_producto(i, dias)[0]) & {"VENCIDO", "POR VENCER"})
        tarjetas(c, [{"titulo": "Valor del inventario (a costo)", "valor": db.dinero(costo), "nivel": "info"},
                     {"titulo": "Ganancia potencial si lo vendes todo", "valor": db.dinero(potencial), "nivel": "ok"},
                     {"titulo": "Productos vencidos o por vencer", "valor": n_alerta, "nivel": "malo" if n_alerta else "ok"}])
        cols = ("ID", "Producto", "Lote", "Unidades", "Costo", "Precio venta", "Margen", "Vence", "Estado")
        tree = crear_tabla(c, cols, (45, 210, 80, 75, 90, 100, 75, 95, 140), 10, izq=("Producto",))
        filas, tags = [], []
        for i in filas_db:
            est, _d = db.estados_producto(i, dias)
            margen = (i["precio_venta"] - i["costo_unitario"]) / i["precio_venta"] * 100
            filas.append((i["id"], i["nombre_producto"], i["lote"], i["cantidad"], db.dinero(i["costo_unitario"]),
                          db.dinero(i["precio_venta"]), f"{margen:.0f}%", i["fecha_vencimiento"], ", ".join(est) or "OK"))
            tags.append(tag_de(est[0]) if est else None)
        llenar(tree, filas, tags)

        def precio():
            iid = seleccionado(tree)
            if iid is None:
                return
            nuevo = simpledialog.askstring("Precio de venta", "Nuevo precio de venta al público ($):", parent=self.root)
            if nuevo:
                self.ejecutar(lambda: db.actualizar_precio_venta(u, iid, nuevo), self.vista_mi_inventario)

        def retirar():
            iid = seleccionado(tree)
            if iid is None:
                return
            if messagebox.askyesno("Retirar producto vencido", "Se retirará este lote de tu inventario y se registrará "
                                   "la pérdida (unidades × costo). ¿Continuar?"):
                ok, perdida = self.ejecutar(lambda: db.retirar_vencido_tienda(u, iid), self.vista_mi_inventario)
                if ok:
                    messagebox.showinfo("Pérdida registrada", f"Pérdida por vencimiento: {db.dinero(perdida)}.")

        acc = tk.Frame(c, bg=FONDO)
        acc.pack(fill="x")
        boton(acc, "✏️ Cambiar precio de venta", precio, "primario")
        boton(acc, "⏳ Retirar vencido (pérdida)", retirar, "aviso")

    # --------------------------------------------------------------- alertas
    def vista_alertas(self, ambito):
        u = self.usuario
        mayorista = ambito == "mayorista"
        dias = db.get_config("dias_alerta_vencimiento", 7)
        c = self.nueva_vista("⚠️ Alertas de inventario" if mayorista else "⚠️ Alertas de mi tienda",
                             f"Vencimientos con {dias} días de anticipación" + (", agotados y stock mínimo" if mayorista else ""))
        lista = db.alertas() if mayorista else db.alertas_tienda(u)
        cuenta = {t: 0 for t in ALERTAS_COLOR}
        for a in lista:
            cuenta[a["tipo"]] += 1
        fila = tk.Frame(c, bg=FONDO)
        fila.pack(fill="x", pady=(0, 10))
        for tipo, n in cuenta.items():
            if mayorista or tipo in ("VENCIDO", "POR VENCER"):
                tk.Label(fila, text=f"{tipo}: {n}", bg=ALERTAS_COLOR[tipo], fg=TEXTO, font=FUENTE_B, padx=14, pady=6).pack(side="left", padx=(0, 8))
        cols = ("Alerta", "Producto", "Lote", "Stock", "Mínimo", "Vence", "Días")
        tree = crear_tabla(c, cols, (120, 250, 90, 70, 70, 100, 150), 13, izq=("Producto",))
        filas = [(a["tipo"], a["nombre"], a["lote"], a["cantidad"], a["stock_minimo"] if a["stock_minimo"] is not None else "—",
                  a["vencimiento"], texto_dias(a["dias"])) for a in lista]
        llenar(tree, filas, [tag_de(a["tipo"]) for a in lista])
        boton(c, "💾 Exportar a CSV", lambda: self.exportar("alertas_inventario", cols, filas), "neutro", "top")
        if not lista:
            tk.Label(c, text="✅ No hay alertas.", font=FUENTE_B, bg=FONDO, fg=COLORES["exito"]).pack(anchor="w")

    # -------------------------------------------------------------- reportes
    def vista_reportes(self):
        c = self.nueva_vista("📊 Reportes", "Resumen del inventario y de los pedidos del mayorista")
        nb = ttk.Notebook(c)
        nb.pack(fill="both", expand=True)

        def pestana(titulo, cols, anchos, filas, izq=()):
            f = tk.Frame(nb, bg=FONDO, padx=10, pady=10)
            nb.add(f, text=titulo)
            tree = crear_tabla(f, cols, anchos, 12, izq=izq)
            llenar(tree, filas)
            boton(f, "💾 Exportar a CSV", lambda: self.exportar(titulo.lower().replace(" ", "_"), cols, filas), "neutro", "top")

        pestana("Resumen", ("Indicador", "Valor"), (380, 220), db.resumen_general(), ("Indicador",))
        venc = [(a["tipo"], a["nombre"], a["lote"], a["cantidad"], a["vencimiento"], texto_dias(a["dias"]))
                for a in db.alertas() if a["tipo"] in ("VENCIDO", "POR VENCER")]
        pestana("Por vencer", ("Estado", "Producto", "Lote", "Stock", "Vence", "Días"), (110, 240, 90, 70, 100, 150), venc, ("Producto",))
        pestana("Más solicitados", ("Producto", "Unidades pedidas", "N° de pedidos", "Valor ($)"), (260, 140, 120, 140),
                [(m["producto"], m["unidades"], m["pedidos"], db.dinero(m["valor"])) for m in db.reporte_mas_solicitados()], ("Producto",))
        pestana("Pedidos por estado", ("Estado", "Cantidad", "Total ($)"), (170, 120, 160),
                [(e["estado"], e["cantidad"], db.dinero(e["total"])) for e in db.reporte_pedidos_por_estado()])
        pestana("Pérdidas por vencimiento", ("Fecha", "Producto", "Lote", "Cant.", "Costo unit.", "Pérdida", "Motivo", "Responsable"),
                (120, 180, 70, 55, 90, 95, 80, 100),
                [(m["fecha"][:16], m["producto"], m["lote"], m["cantidad"], db.dinero(m["costo_unitario"]),
                  db.dinero(m["cantidad"] * m["costo_unitario"]), m["motivo"], m["usuario"]) for m in db.reporte_mermas()], ("Producto",))
        pestana("Movimientos", ("Fecha", "Producto", "Lote", "Tipo", "Cant.", "Detalle", "Responsable"),
                (120, 170, 70, 85, 55, 230, 100),
                [(m["fecha"][:16], m["producto"], m["lote"], m["tipo"], m["cantidad"], m["detalle"], m["usuario"])
                 for m in db.reporte_movimientos()], ("Producto", "Detalle"))

    # -------------------------------------------------------------- ganancias
    def vista_ganancias(self, ambito):
        u = self.usuario
        mayorista = ambito == "mayorista"
        c = self.nueva_vista("💰 Ganancias" if mayorista else "💰 Mis ganancias",
                             "Lo que gana el mayorista al vender a los tenderos" if mayorista
                             else "Lo que ganas al vender a tus compradores, menos lo que pierdes por vencimiento")
        barra = tk.Frame(c, bg=FONDO)
        barra.pack(fill="x", pady=(0, 8))
        tk.Label(barra, text="Periodo:", bg=FONDO, font=FUENTE_B).pack(side="left")
        periodos = ["Todo el tiempo", "Este mes", "Últimos 7 días"]
        combo = ttk.Combobox(barra, state="readonly", values=periodos, width=18)
        combo.set(periodos[0])
        combo.pack(side="left", padx=8)
        zona = tk.Frame(c, bg=FONDO)
        zona.pack(fill="both", expand=True)

        def dibujar(_=None):
            for w in zona.winfo_children():
                w.destroy()
            desde = {"Este mes": date.today().replace(day=1).isoformat(),
                     "Últimos 7 días": (date.today() - timedelta(days=7)).isoformat()}.get(combo.get())
            g = db.ganancias(u, ambito, desde)
            neta_nivel = "ok" if g["ganancia_neta"] >= 0 else "malo"
            tarjetas(zona, [
                {"titulo": "Ventas", "valor": db.dinero(g["ventas"]), "nivel": "info"},
                {"titulo": "Costo de lo vendido", "valor": db.dinero(g["costo"]), "nivel": "info"},
                {"titulo": "Ganancia bruta", "valor": db.dinero(g["ganancia_bruta"]), "nivel": "ok"},
                {"titulo": "Pérdidas por vencimiento", "valor": db.dinero(g["perdidas"]), "nivel": "malo" if g["perdidas"] else "ok"},
                {"titulo": "Ganancia neta", "valor": db.dinero(g["ganancia_neta"]), "nivel": neta_nivel},
                {"titulo": "Margen bruto", "valor": f"{g['margen']:.1f}%", "nivel": "info"}])
            nb = ttk.Notebook(zona)
            nb.pack(fill="both", expand=True)
            f1 = tk.Frame(nb, bg=FONDO, padx=8, pady=8)
            nb.add(f1, text="Por producto")
            cols = ("Producto", "Unidades", "Ventas", "Costo", "Ganancia", "Margen")
            t1 = crear_tabla(f1, cols, (260, 90, 110, 110, 110, 80), 7, izq=("Producto",))
            filas = [(f["producto"], f["unidades"], db.dinero(f["ventas"]), db.dinero(f["costo"]),
                      db.dinero(f["ganancia"]), f"{f['margen']:.0f}%") for f in g["filas"]]
            llenar(t1, filas)
            boton(f1, "💾 Exportar a CSV", lambda: self.exportar("ganancias", cols, filas), "neutro", "top")
            f2 = tk.Frame(nb, bg=FONDO, padx=8, pady=8)
            nb.add(f2, text="Pérdidas por vencimiento")
            t2 = crear_tabla(f2, ("Fecha", "Producto", "Lote", "Cant.", "Costo unit.", "Pérdida"), (130, 220, 80, 60, 100, 110), 7,
                             izq=("Producto",))
            llenar(t2, [(m["fecha"][:16], m["producto"], m["lote"], m["cantidad"], db.dinero(m["costo_unitario"]),
                         db.dinero(m["cantidad"] * m["costo_unitario"]))
                        for m in db.reporte_mermas(None if mayorista else u, desde)])

        combo.bind("<<ComboboxSelected>>", dibujar)
        dibujar()

    # --------------------------------------------------------- administración
    def vista_admin(self):
        c = self.nueva_vista("👥 Administración", "Usuarios del sistema y parámetros de alertas")
        tree = crear_tabla(c, ("ID", "Usuario", "Rol", "Tienda", "Dirección", "Activo"), (45, 120, 120, 220, 270, 70), 7,
                           izq=("Tienda", "Dirección"))

        def cargar():
            llenar(tree, [(u["id"], u["usuario"], u["rol"], u["nombre_tienda"], u["direccion"], "Sí" if u["activo"] else "No")
                          for u in db.listar_usuarios()])

        def crear():
            def guardar(v):
                db.crear_usuario(v["usuario"], v["clave"], v["rol"], v["tienda"], v["dir"])
                cargar()

            Formulario(self.root, "Nuevo usuario", [
                ("usuario", "Usuario:", "", None), ("clave", "Contraseña:", "", "*"),
                ("rol", "Rol:", "Tendero", list(db.ROLES)), ("tienda", "Nombre de la tienda:", "", None),
                ("dir", "Dirección:", "", None)], guardar, "Crear usuario")

        def alternar():
            uid = seleccionado(tree)
            if uid is None:
                return
            if uid == self.usuario["id"]:
                messagebox.showerror("No permitido", "No puedes desactivar tu propia cuenta.")
                return
            actual = next(u for u in db.listar_usuarios() if u["id"] == uid)["activo"]
            db.set_activo(uid, not actual)
            cargar()

        def clave():
            uid = seleccionado(tree)
            if uid is None:
                return
            nueva = simpledialog.askstring("Cambiar contraseña", "Nueva contraseña (mín. 4 caracteres):", show="*", parent=self.root)
            if nueva is not None:
                self.ejecutar(lambda: db.cambiar_clave(uid, nueva), exito="Contraseña actualizada.")

        acc = tk.Frame(c, bg=FONDO)
        acc.pack(fill="x")
        boton(acc, "➕ Nuevo usuario", crear, "exito")
        boton(acc, "🔁 Activar / desactivar", alternar, "neutro")
        boton(acc, "🔑 Cambiar contraseña", clave, "primario")

        card = tk.Frame(c, bg=BLANCO, highlightthickness=1, highlightbackground=BORDE, padx=22, pady=16)
        card.pack(fill="x", pady=(14, 0))
        tk.Label(card, text="Parámetros de alertas", font=("Segoe UI", 12, "bold"), bg=BLANCO, fg=TEXTO).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        tk.Label(card, text="Días de anticipación para alertar vencimientos:", bg=BLANCO, font=FUENTE).grid(row=1, column=0, sticky="w", pady=4)
        e_dias = entrada(card, 8)
        e_dias.insert(0, db.get_config("dias_alerta_vencimiento", 7))
        e_dias.grid(row=1, column=1, padx=10, ipady=3)
        tk.Label(card, text="Stock mínimo por defecto al registrar productos:", bg=BLANCO, font=FUENTE).grid(row=2, column=0, sticky="w", pady=4)
        e_min = entrada(card, 8)
        e_min.insert(0, db.get_config("stock_minimo_defecto", 10))
        e_min.grid(row=2, column=1, padx=10, ipady=3)
        Boton(card, "Guardar parámetros", lambda: self.ejecutar(
            lambda: db.guardar_configuracion(e_dias.get(), e_min.get()), None, "Parámetros guardados."), "exito").grid(
            row=1, column=2, rowspan=2, padx=(20, 0))
        cargar()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()