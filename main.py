"""Sistema de Inventario Mayorista — interfaz gráfica (Tkinter).

Ejecutar:  python main.py
Las reglas de negocio están en database.py; aquí solo hay interfaz.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import database as db

BG = "#f8f9fa"
COLORES_ALERTA = {"VENCIDO": "#f5c6cb", "POR VENCER": "#ffe0b2", "AGOTADO": "#d6d8db", "STOCK BAJO": "#fff3cd"}
FUENTE = ("Arial", 10)


def tag_de(tipo):
    return tipo.replace(" ", "_")


def crear_tabla(padre, columnas, anchos=None, alto=12):
    marco = tk.Frame(padre, bg=BG)
    marco.pack(fill="both", expand=True, padx=8, pady=4)
    tree = ttk.Treeview(marco, columns=columnas, show="headings", height=alto)
    sb = ttk.Scrollbar(marco, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    for i, col in enumerate(columnas):
        tree.heading(col, text=col)
        tree.column(col, width=anchos[i] if anchos else 110, anchor="center")
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    for tipo, color in COLORES_ALERTA.items():
        tree.tag_configure(tag_de(tipo), background=color)
    return tree


def llenar(tree, filas, tags=None):
    tree.delete(*tree.get_children())
    for i, fila in enumerate(filas):
        tree.insert("", "end", values=fila, tags=(tags[i],) if tags and tags[i] else ())


def seleccionado(tree, mensaje="Selecciona una fila de la tabla."):
    sel = tree.selection()
    if not sel:
        messagebox.showwarning("Selección", mensaje)
        return None
    return int(tree.item(sel[0])["values"][0])


def boton(padre, texto, comando, color="#007bff", lado="left"):
    b = tk.Button(padre, text=texto, command=comando, bg=color, fg="white" if color != "#ffc107" else "black",
                  font=("Arial", 9, "bold"), padx=8, pady=2)
    b.pack(side=lado, padx=5, pady=4)
    return b


class Formulario(tk.Toplevel):
    """Ventana modal genérica. campos = [(clave, etiqueta, valor_inicial, opcion)]
    donde opcion puede ser None, '*' (contraseña) o una lista (lista desplegable)."""

    def __init__(self, padre, titulo, campos, al_guardar, texto_boton="Guardar"):
        super().__init__(padre)
        self.title(titulo)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(padre)
        self.grab_set()
        self.widgets = {}
        for i, (clave, etiqueta, inicial, opcion) in enumerate(campos):
            tk.Label(self, text=etiqueta, bg=BG, anchor="w", font=FUENTE).grid(row=i, column=0, sticky="w", padx=10, pady=4)
            if isinstance(opcion, (list, tuple)):
                w = ttk.Combobox(self, values=opcion, state="readonly", width=28)
                w.set(inicial)
            else:
                w = tk.Entry(self, width=31, show="*" if opcion == "*" else "")
                w.insert(0, inicial)
            w.grid(row=i, column=1, padx=10, pady=4)
            self.widgets[clave] = w
        self.al_guardar = al_guardar
        tk.Button(self, text=texto_boton, command=self.guardar, bg="#28a745", fg="white",
                  font=("Arial", 10, "bold")).grid(row=len(campos), column=0, columnspan=2, pady=12)

    def guardar(self):
        valores = {k: w.get().strip() for k, w in self.widgets.items()}
        try:
            self.al_guardar(valores)
        except db.ErrorNegocio as e:
            messagebox.showerror("Revisa los datos", str(e), parent=self)
            return
        self.destroy()


class App:
    def __init__(self, root):
        self.root = root
        root.title("Sistema de Inventario Mayorista")
        root.geometry("1120x700")
        root.minsize(1000, 620)
        db.init_db()
        self.usuario = None
        self.carrito = []
        self.mostrar_login()

    # ------------------------------------------------------------------ util
    def limpiar_root(self):
        for w in self.root.winfo_children():
            w.destroy()

    def ejecutar(self, accion, despues=None, exito=None):
        """Ejecuta una acción de db mostrando los errores de negocio. Devuelve (ok, resultado)."""
        try:
            res = accion()
        except db.ErrorNegocio as e:
            messagebox.showerror("No se pudo completar", str(e))
            return False, None
        if exito:
            messagebox.showinfo("Listo", exito)
        if despues:
            despues()
        self.actualizar_alertas()
        return True, res

    def nueva_vista(self, titulo):
        for w in self.contenido.winfo_children():
            w.destroy()
        tk.Label(self.contenido, text=titulo, font=("Arial", 13, "bold"), bg=BG).pack(pady=(8, 4))
        return self.contenido

    def exportar(self, nombre, columnas, filas):
        ruta = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=f"{nombre}.csv",
                                            filetypes=[("CSV (Excel)", "*.csv")])
        if ruta:
            db.exportar_csv(ruta, columnas, filas)
            messagebox.showinfo("Exportado", f"Archivo guardado en:\n{ruta}")

    # ----------------------------------------------------------------- login
    def mostrar_login(self):
        self.limpiar_root()
        self.usuario = None
        self.carrito = []
        self.root.config(bg="#f0f2f5")
        f = tk.Frame(self.root, bg="#f0f2f5")
        f.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(f, text="SISTEMA DE INVENTARIO MAYORISTA", font=("Arial", 16, "bold"), bg="#f0f2f5").grid(columnspan=2, pady=(0, 4))
        tk.Label(f, text="Soledad y Barranquilla", font=("Arial", 10), fg="gray", bg="#f0f2f5").grid(columnspan=2, pady=(0, 18))
        tk.Label(f, text="Usuario:", bg="#f0f2f5", font=("Arial", 11)).grid(row=2, column=0, sticky="w", pady=5)
        e_user = tk.Entry(f, font=("Arial", 11), width=22)
        e_user.grid(row=2, column=1, pady=5)
        tk.Label(f, text="Contraseña:", bg="#f0f2f5", font=("Arial", 11)).grid(row=3, column=0, sticky="w", pady=5)
        e_clave = tk.Entry(f, font=("Arial", 11), width=22, show="*")
        e_clave.grid(row=3, column=1, pady=5)

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

        tk.Button(f, text="Entrar", command=entrar, bg="#007bff", fg="white", font=("Arial", 11, "bold"),
                  width=18).grid(row=4, columnspan=2, pady=18)
        e_user.bind("<Return>", entrar)
        e_clave.bind("<Return>", entrar)
        e_user.focus()

    # ------------------------------------------------------------- principal
    def mostrar_principal(self, usuario):
        self.limpiar_root()
        self.usuario = usuario
        self.carrito = []
        self.root.config(bg=BG)
        self.es_mayorista = usuario["rol"] in db.ROLES_MAYORISTA
        self.btn_alertas = None

        cab = tk.Frame(self.root, bg="#343a40", pady=8)
        cab.pack(fill="x")
        tk.Label(cab, text=f"{usuario['usuario']} [{usuario['rol']}]  |  {usuario['tienda']} — {usuario['direccion']}",
                 font=("Arial", 10, "bold"), bg="#343a40", fg="white").pack(side="left", padx=12)
        tk.Button(cab, text="Cerrar sesión", command=self.mostrar_login, bg="#dc3545", fg="white",
                  font=("Arial", 9, "bold")).pack(side="right", padx=12)

        menu = tk.Frame(self.root, bg="#e9ecef", pady=4)
        menu.pack(fill="x")
        self.contenido = tk.Frame(self.root, bg=BG)
        self.contenido.pack(fill="both", expand=True, padx=8, pady=6)

        if self.es_mayorista:
            opciones = [("📦 Inventario", self.vista_inventario, "#6c757d"),
                        ("➕ Registrar producto", self.vista_registro, "#28a745"),
                        ("📋 Pedidos", lambda: self.vista_pedidos(False), "#ffc107"),
                        ("🗂️ Historial", lambda: self.vista_pedidos(True), "#17a2b8"),
                        ("⚠️ Alertas", self.vista_alertas, "#dc3545"),
                        ("📊 Reportes", self.vista_reportes, "#6f42c1")]
            if usuario["rol"] == "Administrador":
                # El administrador ve TODAS las pestañas (también las de tendero) para poder probar el sistema
                opciones.insert(2, ("🛒 Hacer pedido", self.vista_catalogo, "#007bff"))
                opciones.append(("📦 Mi inventario", self.vista_mi_inventario, "#6c757d"))
                opciones.append(("👥 Administración", self.vista_admin, "#343a40"))
        else:
            opciones = [("🛒 Hacer pedido", self.vista_catalogo, "#007bff"),
                        ("📋 Mis pedidos", lambda: self.vista_pedidos(False), "#ffc107"),
                        ("🗂️ Historial", lambda: self.vista_pedidos(True), "#17a2b8"),
                        ("📦 Mi inventario", self.vista_mi_inventario, "#6c757d")]
        por_fila = 5 if len(opciones) > 6 else len(opciones)   # el menú del admin ocupa dos filas
        for ini in range(0, len(opciones), por_fila):
            fila = tk.Frame(menu, bg="#e9ecef")
            fila.pack(fill="x")
            for texto, cmd, color in opciones[ini:ini + por_fila]:
                b = boton(fila, texto, cmd, color)
                if "Alertas" in texto:
                    self.btn_alertas = b

        self.actualizar_alertas()
        (self.vista_inventario if self.es_mayorista else self.vista_catalogo)()
        if self.es_mayorista:
            self.aviso_inicial()

    def actualizar_alertas(self):
        if self.btn_alertas is not None and self.btn_alertas.winfo_exists():
            total = sum(db.resumen_alertas().values())
            self.btn_alertas.config(text=f"⚠️ Alertas ({total})")

    def aviso_inicial(self):
        r = db.resumen_alertas()
        if sum(r.values()):
            dias = db.get_config("dias_alerta_vencimiento", 15)
            messagebox.showwarning(
                "Alertas de inventario",
                f"Vencidos con existencias: {r['VENCIDO']}\n"
                f"Por vencer (próximos {dias} días): {r['POR VENCER']}\n"
                f"Agotados: {r['AGOTADO']}\n"
                f"Con stock bajo: {r['STOCK BAJO']}\n\nRevisa la pestaña «Alertas».")

    # ------------------------------------------------- mayorista: inventario
    def vista_inventario(self):
        c = self.nueva_vista("📦 Inventario del mayorista")
        barra = tk.Frame(c, bg=BG)
        barra.pack(fill="x", padx=8)
        tk.Label(barra, text="🔍 Buscar producto o lote:", bg=BG, font=FUENTE).pack(side="left")
        buscar = tk.StringVar()
        tk.Entry(barra, textvariable=buscar, width=30).pack(side="left", padx=6)
        cols = ("ID", "Producto", "Lote", "Stock", "Mínimo", "P. mayorista", "P. sugerido", "Vence", "Estado")
        tree = crear_tabla(c, cols, (45, 190, 80, 65, 65, 100, 100, 95, 160), 15)
        dias_alerta = int(db.get_config("dias_alerta_vencimiento", 15))

        def cargar(*_):
            filas, tags = [], []
            for p in db.listar_productos(buscar.get().strip()):
                est, _d = db.estados_producto(p, dias_alerta)
                filas.append((p["id"], p["nombre"], p["lote"], p["cantidad"], p["stock_minimo"],
                              db.dinero(p["precio_mayorista"]), db.dinero(p["precio_sugerido"]),
                              p["fecha_vencimiento"], ", ".join(est) or "OK"))
                tags.append(tag_de(est[0]) if est else None)
            llenar(tree, filas, tags)

        buscar.trace_add("write", cargar)

        def reponer():
            pid = seleccionado(tree)
            if pid is None:
                return
            n = simpledialog.askinteger("Reponer stock", "Unidades que ingresan a bodega:",
                                        parent=self.root, minvalue=1)
            if n:
                self.ejecutar(lambda: db.reponer_stock(pid, n, self.usuario["usuario"]), cargar,
                              "Stock actualizado.")

        def editar():
            pid = seleccionado(tree)
            if pid is None:
                return
            p = db.obtener_producto(pid)

            def guardar(v):
                db.editar_producto(pid, v["min"], v["pm"], v["ps"], v["venc"], self.usuario["usuario"])
                cargar()
                self.actualizar_alertas()

            Formulario(self.root, f"Editar: {p['nombre']} (lote {p['lote']})", [
                ("min", "Stock mínimo:", p["stock_minimo"], None),
                ("pm", "Precio mayorista ($):", int(p["precio_mayorista"]), None),
                ("ps", "Precio sugerido ($):", int(p["precio_sugerido"]), None),
                ("venc", "Vencimiento (AAAA-MM-DD):", p["fecha_vencimiento"], None)], guardar)

        def baja():
            pid = seleccionado(tree)
            if pid is None:
                return
            if messagebox.askyesno("Confirmar", "¿Dar de baja este producto del catálogo?\n"
                                   "Se conserva su historial de movimientos."):
                self.ejecutar(lambda: db.dar_de_baja(pid, self.usuario["usuario"]), cargar)

        acc = tk.Frame(c, bg=BG)
        acc.pack(fill="x")
        boton(acc, "➕ Reponer stock", reponer, "#28a745")
        boton(acc, "✏️ Editar", editar, "#007bff")
        boton(acc, "🗑️ Dar de baja", baja, "#dc3545", "right")
        cargar()

    def vista_registro(self):
        c = self.nueva_vista("➕ Registrar nuevo producto / lote")
        f = tk.Frame(c, bg=BG)
        f.pack(pady=10)
        campos = [("nombre", "Nombre del producto:", ""), ("lote", "Número de lote:", ""),
                  ("cant", "Cantidad que ingresa:", ""),
                  ("min", "Stock mínimo (alerta):", db.get_config("stock_minimo_defecto", 10)),
                  ("pm", "Precio mayorista ($):", ""), ("ps", "Precio sugerido al público ($):", ""),
                  ("venc", "Vencimiento (AAAA-MM-DD):", "")]
        ents = {}
        for i, (k, etiqueta, inicial) in enumerate(campos):
            tk.Label(f, text=etiqueta, bg=BG, font=FUENTE).grid(row=i, column=0, sticky="w", pady=5, padx=6)
            e = tk.Entry(f, width=30)
            e.insert(0, inicial)
            e.grid(row=i, column=1, pady=5)
            ents[k] = e

        def guardar():
            v = {k: e.get() for k, e in ents.items()}
            ok, _ = self.ejecutar(lambda: db.registrar_producto(
                v["nombre"], v["lote"], v["cant"], v["min"], v["pm"], v["ps"], v["venc"],
                self.usuario["usuario"]), exito="Producto registrado en el inventario.")
            if ok:
                for k in ("nombre", "lote", "cant", "pm", "ps", "venc"):
                    ents[k].delete(0, tk.END)

        boton(c, "💾 Guardar en inventario", guardar, "#28a745", "top")

    # ----------------------------------------------- minorista: hacer pedido
    def vista_catalogo(self):
        u = self.usuario
        c = self.nueva_vista(f"🛒 Hacer pedido — {u['tienda']}   (entrega en: {u['direccion']})")
        cols = ("ID", "Producto", "Lote", "Disponible", "P. mayorista", "P. sugerido", "Vence")
        cat = crear_tabla(c, cols, (45, 210, 90, 90, 110, 110, 100), 7)
        llenar(cat, [(p["id"], p["nombre"], p["lote"], p["cantidad"], db.dinero(p["precio_mayorista"]),
                      db.dinero(p["precio_sugerido"]), p["fecha_vencimiento"])
                     for p in db.listar_productos(solo_disponibles=True)])

        fila = tk.Frame(c, bg=BG)
        fila.pack(fill="x", padx=8)
        tk.Label(fila, text="Cantidad:", bg=BG, font=FUENTE).pack(side="left")
        e_cant = tk.Entry(fila, width=8)
        e_cant.pack(side="left", padx=6)
        tk.Label(fila, text="Tu precio de venta al público ($):", bg=BG, font=FUENTE).pack(side="left", padx=(10, 0))
        e_pub = tk.Entry(fila, width=10)
        e_pub.pack(side="left", padx=6)

        def al_elegir(_=None):
            sel = cat.selection()
            if sel:
                p = db.obtener_producto(int(cat.item(sel[0])["values"][0]))
                e_pub.delete(0, tk.END)
                e_pub.insert(0, int(p["precio_sugerido"]))

        cat.bind("<<TreeviewSelect>>", al_elegir)

        cols_c = ("ID", "Producto", "Lote", "Cant.", "P. unitario", "Subtotal", "Venta al público")
        tk.Label(c, text="🧺 Tu pedido", font=("Arial", 11, "bold"), bg=BG).pack(pady=(8, 0))
        carro = crear_tabla(c, cols_c, (45, 210, 90, 60, 110, 110, 120), 5)
        lbl_total = tk.Label(c, text="", font=("Arial", 11, "bold"), bg=BG)

        def refrescar():
            llenar(carro, [(i["id"], i["nombre"], i["lote"], i["cant"], db.dinero(i["precio"]),
                            db.dinero(i["cant"] * i["precio"]), db.dinero(i["pub"])) for i in self.carrito])
            lbl_total.config(text=f"Total a pagar al mayorista: "
                                  f"{db.dinero(sum(i['cant'] * i['precio'] for i in self.carrito))}")

        def agregar():
            pid = seleccionado(cat, "Selecciona un producto del catálogo.")
            if pid is None:
                return
            p = db.obtener_producto(pid)
            try:
                cant = db.validar_entero(e_cant.get(), "La cantidad", 1)
                pub = db.validar_numero(e_pub.get(), "El precio al público")
            except db.ErrorNegocio as e:
                messagebox.showerror("Revisa los datos", str(e))
                return
            ya = sum(i["cant"] for i in self.carrito if i["id"] == pid)
            if ya + cant > p["cantidad"]:
                messagebox.showerror("Stock", f"Solo hay {p['cantidad']} unidades disponibles (ya tienes {ya} en el pedido).")
                return
            for i in self.carrito:
                if i["id"] == pid:
                    i["cant"] += cant
                    i["pub"] = pub
                    break
            else:
                self.carrito.append({"id": pid, "nombre": p["nombre"], "lote": p["lote"], "cant": cant,
                                     "precio": p["precio_mayorista"], "pub": pub})
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
            if not messagebox.askyesno("Confirmar", "¿Enviar la solicitud de pedido al mayorista?"):
                return
            ok, pedido_id = self.ejecutar(lambda: db.crear_pedido(
                u, [(i["id"], i["cant"], i["pub"]) for i in self.carrito]))
            if ok:
                self.carrito = []
                messagebox.showinfo("Pedido enviado", f"Pedido #{pedido_id} enviado.\n"
                                    "Queda PENDIENTE hasta que el mayorista lo apruebe.")
                self.vista_catalogo()

        acc = tk.Frame(c, bg=BG)
        acc.pack(fill="x")
        boton(acc, "➕ Agregar al pedido", agregar, "#28a745")
        boton(acc, "➖ Quitar", quitar, "#6c757d")
        boton(acc, "📨 Enviar pedido", enviar, "#007bff", "right")
        lbl_total.pack(side="bottom", pady=4)
        refrescar()

    def vista_mi_inventario(self):
        c = self.nueva_vista(f"📦 Inventario de tu tienda: {self.usuario['tienda']}")
        tree = crear_tabla(c, ("Producto", "Unidades", "Precio de venta"), (320, 120, 160), 15)
        llenar(tree, [(i["nombre_producto"], i["cantidad"], db.dinero(i["precio_venta"]))
                      for i in db.inventario_tienda(self.usuario)])
        tk.Label(c, text="Se actualiza automáticamente cuando confirmas la llegada de un pedido.",
                 bg=BG, fg="gray").pack()

    # --------------------------------------------------------------- pedidos
    def vista_pedidos(self, historial):
        mayorista = self.es_mayorista
        if historial:
            titulo = "🗂️ Historial de pedidos y entregas"
            estados = db.ESTADOS_FINALES
        else:
            titulo = "📋 Pedidos en curso" if mayorista else "📋 Mis pedidos en curso"
            estados = db.ESTADOS_ACTIVOS
        c = self.nueva_vista(titulo)
        cols = ("ID", "Fecha", "Cliente", "Tienda", "Dirección", "Productos", "Total", "Estado")
        tree = crear_tabla(c, cols, (45, 130, 80, 130, 150, 270, 90, 100), 14)

        def cargar():
            llenar(tree, [(p["id"], p["fecha_creacion"][:16], p["usuario"], p["tienda"], p["direccion"],
                           p["resumen"], db.dinero(p["total"]), p["estado"])
                          for p in db.listar_pedidos(self.usuario, estados)])

        def cambiar(nuevo, mensaje):
            pid = seleccionado(tree, "Selecciona un pedido de la tabla.")
            if pid is None:
                return
            detalle = ""
            if nuevo == "RECHAZADO":
                detalle = simpledialog.askstring("Rechazar pedido", "Motivo (opcional):", parent=self.root)
                if detalle is None:
                    return
            elif not messagebox.askyesno("Confirmar", f"¿{mensaje} el pedido #{pid}?"):
                return
            self.ejecutar(lambda: db.cambiar_estado(pid, nuevo, self.usuario, detalle), cargar,
                          f"Pedido #{pid}: {nuevo}.")

        def ver():
            pid = seleccionado(tree, "Selecciona un pedido de la tabla.")
            if pid is not None:
                self.detalle_pedido(pid)

        acc = tk.Frame(c, bg=BG)
        acc.pack(fill="x")
        if not historial:
            if mayorista:
                boton(acc, "✅ Aprobar", lambda: cambiar("APROBADO", "Aprobar"), "#28a745")
                boton(acc, "❌ Rechazar", lambda: cambiar("RECHAZADO", "Rechazar"), "#dc3545")
                boton(acc, "🚚 Marcar despachado", lambda: cambiar("DESPACHADO", "Marcar como despachado"), "#17a2b8")
            if not mayorista or self.usuario["rol"] == "Administrador":
                boton(acc, "📥 Confirmar llegada a la tienda", lambda: cambiar("ENTREGADO", "Confirmar la llegada de"), "#17a2b8")
                boton(acc, "🚫 Cancelar pedido", lambda: cambiar("CANCELADO", "Cancelar"), "#dc3545")
        boton(acc, "🔎 Ver detalle", ver, "#6c757d", "right")
        tree.bind("<Double-1>", lambda _e: ver())
        cargar()

    def detalle_pedido(self, pedido_id):
        win = tk.Toplevel(self.root)
        win.title(f"Pedido #{pedido_id}")
        win.configure(bg=BG)
        win.geometry("760x520")
        tk.Label(win, text=f"Pedido #{pedido_id} — productos", font=("Arial", 11, "bold"), bg=BG).pack(pady=(10, 0))
        t1 = crear_tabla(win, ("Producto", "Lote", "Cant.", "P. unitario", "Subtotal", "Venta al público"),
                         (210, 90, 60, 100, 100, 120), 6)
        llenar(t1, [(i["nombre_producto"], i["lote"], i["cantidad"], db.dinero(i["precio_unitario"]),
                     db.dinero(i["cantidad"] * i["precio_unitario"]), db.dinero(i["precio_publico"]))
                    for i in db.items_pedido(pedido_id)])
        tk.Label(win, text="Seguimiento (historial de estados)", font=("Arial", 11, "bold"), bg=BG).pack(pady=(10, 0))
        t2 = crear_tabla(win, ("Fecha", "Estado", "Usuario", "Detalle"), (150, 110, 100, 300), 6)
        llenar(t2, [(h["fecha"], h["estado"], h["usuario"], h["detalle"]) for h in db.historial_pedido(pedido_id)])

    # --------------------------------------------------------------- alertas
    def vista_alertas(self):
        dias = db.get_config("dias_alerta_vencimiento", 15)
        c = self.nueva_vista(f"⚠️ Alertas de inventario (vencimiento: próximos {dias} días)")
        r = db.resumen_alertas()
        fila = tk.Frame(c, bg=BG)
        fila.pack(pady=4)
        for tipo, n in r.items():
            tk.Label(fila, text=f"{tipo}: {n}", bg=COLORES_ALERTA[tipo], font=("Arial", 10, "bold"),
                     padx=12, pady=4).pack(side="left", padx=6)
        cols = ("Alerta", "Producto", "Lote", "Stock", "Mínimo", "Vence", "Días")
        tree = crear_tabla(c, cols, (110, 220, 90, 70, 70, 100, 140), 14)
        filas, tags = [], []
        for a in db.alertas():
            d = a["dias"]
            txt = f"vencido hace {-d} d" if d < 0 else ("vence hoy" if d == 0 else f"faltan {d} d")
            filas.append((a["tipo"], a["nombre"], a["lote"], a["cantidad"], a["stock_minimo"], a["vencimiento"], txt))
            tags.append(tag_de(a["tipo"]))
        llenar(tree, filas, tags)
        boton(c, "💾 Exportar a CSV", lambda: self.exportar("alertas_inventario", cols, filas), "#6c757d", "top")

    # -------------------------------------------------------------- reportes
    def vista_reportes(self):
        c = self.nueva_vista("📊 Reportes")
        nb = ttk.Notebook(c)
        nb.pack(fill="both", expand=True, padx=6, pady=4)

        def pestana(titulo, cols, anchos, filas):
            f = tk.Frame(nb, bg=BG)
            nb.add(f, text=titulo)
            tree = crear_tabla(f, cols, anchos, 14)
            llenar(tree, filas)
            boton(f, "💾 Exportar a CSV", lambda: self.exportar(titulo.lower().replace(" ", "_"), cols, filas),
                  "#6c757d", "top")

        pestana("Resumen", ("Indicador", "Valor"), (360, 200), db.resumen_general())
        venc = [(a["tipo"], a["nombre"], a["lote"], a["cantidad"], a["vencimiento"], a["dias"])
                for a in db.alertas() if a["tipo"] in ("VENCIDO", "POR VENCER")]
        pestana("Por vencer", ("Estado", "Producto", "Lote", "Stock", "Vence", "Días"),
                (110, 230, 90, 70, 100, 70), venc)
        pestana("Más solicitados", ("Producto", "Unidades pedidas", "N° de pedidos", "Valor ($)"), (250, 130, 110, 130),
                [(m["producto"], m["unidades"], m["pedidos"], db.dinero(m["valor"])) for m in db.reporte_mas_solicitados()])
        pestana("Pedidos por estado", ("Estado", "Cantidad", "Total ($)"), (160, 110, 150),
                [(e["estado"], e["cantidad"], db.dinero(e["total"])) for e in db.reporte_pedidos_por_estado()])
        pestana("Movimientos", ("Fecha", "Producto", "Lote", "Tipo", "Cant.", "Detalle", "Responsable"),
                (130, 170, 70, 80, 60, 230, 100),
                [(m["fecha"][:16], m["producto"], m["lote"], m["tipo"], m["cantidad"], m["detalle"], m["usuario"])
                 for m in db.reporte_movimientos()])

    # ---------------------------------------------------------- administración
    def vista_admin(self):
        c = self.nueva_vista("👥 Administración: usuarios y parámetros")
        cols = ("ID", "Usuario", "Rol", "Tienda", "Dirección", "Activo")
        tree = crear_tabla(c, cols, (45, 110, 110, 190, 230, 70), 8)

        def cargar():
            llenar(tree, [(u["id"], u["usuario"], u["rol"], u["nombre_tienda"], u["direccion"],
                           "Sí" if u["activo"] else "No") for u in db.listar_usuarios()])

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
            nueva = simpledialog.askstring("Cambiar contraseña", "Nueva contraseña (mín. 4 caracteres):",
                                           show="*", parent=self.root)
            if nueva is not None:
                self.ejecutar(lambda: db.cambiar_clave(uid, nueva), exito="Contraseña actualizada.")

        acc = tk.Frame(c, bg=BG)
        acc.pack(fill="x")
        boton(acc, "➕ Nuevo usuario", crear, "#28a745")
        boton(acc, "🔁 Activar / desactivar", alternar, "#6c757d")
        boton(acc, "🔑 Cambiar contraseña", clave, "#007bff")

        caja = tk.LabelFrame(c, text=" Parámetros de alertas ", bg=BG, font=("Arial", 10, "bold"), padx=10, pady=8)
        caja.pack(fill="x", padx=10, pady=12)
        tk.Label(caja, text="Días de anticipación para alertar vencimientos:", bg=BG, font=FUENTE).grid(row=0, column=0, sticky="w", pady=3)
        e_dias = tk.Entry(caja, width=8)
        e_dias.insert(0, db.get_config("dias_alerta_vencimiento", 15))
        e_dias.grid(row=0, column=1, padx=8)
        tk.Label(caja, text="Stock mínimo por defecto al registrar productos:", bg=BG, font=FUENTE).grid(row=1, column=0, sticky="w", pady=3)
        e_min = tk.Entry(caja, width=8)
        e_min.insert(0, db.get_config("stock_minimo_defecto", 10))
        e_min.grid(row=1, column=1, padx=8)
        tk.Button(caja, text="Guardar parámetros", bg="#28a745", fg="white", font=("Arial", 9, "bold"),
                  command=lambda: self.ejecutar(lambda: db.guardar_configuracion(e_dias.get(), e_min.get()),
                                                exito="Parámetros guardados.")).grid(row=2, column=0, columnspan=2, pady=6)
        cargar()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
