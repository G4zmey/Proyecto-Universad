# Sistema de Inventario para Distribuidoras Mayoristas
Soledad y Barranquilla · Python 3.9+ · Tkinter + SQLite (sin librerías externas)

## Cómo ejecutarlo
```
python main.py        # abre el sistema
python pruebas.py     # corre las 20 pruebas automáticas de las reglas de negocio
```
En la primera ejecución se crea `inventario_mayorista_v2.db` con usuarios y productos de
demostración (con fechas relativas a hoy, para que las alertas se vean de inmediato).
Para empezar de cero, borra ese archivo. *(No reutiliza la base de datos de la versión anterior.)*

| Usuario | Contraseña | Rol |
|---|---|---|
| admin | admin123 | Administrador |
| vendedor | 1234 | Vendedor mayorista |
| tendero | 1234 | Tendero (minorista) |
| comprador | 1234 | Comprador minorista |

> Son cuentas de demostración. Cambia las contraseñas desde **Administración** antes de usarlo en serio.

## Estructura
- `database.py`: base de datos, validaciones, estados de pedidos, alertas y reportes (sin interfaz).
- `main.py`: interfaz Tkinter.
- `pruebas.py`: pruebas automáticas.

## Alcance del documento → dónde está en el sistema
| Alcance preliminar | Implementación |
|---|---|
| Registro y consulta de productos, cantidades, lotes y vencimientos | **Inventario** y **Registrar producto** (editar, reponer, dar de baja) |
| Alertas de stock mínimo y productos próximos a vencer | **Alertas** (VENCIDO, POR VENCER, AGOTADO, STOCK BAJO), contador en el menú y aviso al iniciar sesión |
| Acceso diferenciado mayorista / minorista | Menús y permisos por rol (validados también en `database.py`) |
| Realización y aprobación de pedidos | Carrito de varios productos → el mayorista aprueba o rechaza |
| Historial de pedidos y entregas | **Historial** + detalle con seguimiento de cada cambio de estado |
| Reportes de por vencer y más solicitados | **Reportes** (resumen, por vencer, más solicitados, por estado, movimientos) con exportación a CSV |

## Flujo de un pedido
`PENDIENTE` → `APROBADO` (descuenta stock) → `DESPACHADO` → `ENTREGADO` (suma al inventario de la tienda).
Desde `PENDIENTE` también puede ser `RECHAZADO` (mayorista) o `CANCELADO` (quien lo hizo).
No se permiten otros saltos, así que ya no se puede duplicar mercancía ni revertir pedidos aprobados.

## Decisiones sobre las preguntas pendientes (ajústalas con tus clientes)
1. **Entradas y salidas:** el sistema las registra solas en `movimientos` (entrada al registrar o reponer, salida al aprobar un pedido), con fecha y responsable.
2. **Stock mínimo:** se define por producto al registrarlo; el valor por defecto se configura en Administración (10 unidades).
3. **Anticipación de vencimiento:** configurable en Administración (15 días por defecto).
4. **Responsable del inventario:** Administrador y Vendedor; cada movimiento queda con su nombre.
5. **Permisos:**
   - Administrador: todo, más usuarios y parámetros. Ve todas las pestañas y también puede actuar como tendero
     (hacer pedidos, confirmar llegadas), para probar el flujo completo desde un solo usuario.
   - Vendedor: inventario, pedidos, alertas y reportes.
   - Tendero y Comprador: ver el catálogo disponible, hacer y cancelar sus pedidos, confirmar llegadas y ver su propio inventario e historial.
6. **Recursos:** solo Python (incluye Tkinter y SQLite); sin costo de licencias.

## Qué se corrigió respecto a la versión anterior
Contraseñas con hash (PBKDF2) · pedidos con varios productos y vinculados por ID de lote · stock revalidado al aprobar ·
confirmar llegada solo si el pedido fue despachado y una sola vez · el inventario de la tienda suma en vez de duplicar filas ·
fechas validadas (AAAA-MM-DD) y no se registra mercancía vencida · baja lógica en lugar de borrar · precio al público en su propia columna.

## Limitaciones conocidas
Aplicación de escritorio de un solo equipo (SQLite local): para varias sedes en red habría que migrar a un servidor de base de datos.
Los productos se manejan por lote sin lógica automática de "primero en vencer, primero en salir": el tendero elige el lote.
