Actúa como arquitecto principal + tech lead + staff engineer y coordina subagentes en paralelo para diseñar e implementar un nuevo microservicio TMS/WMS completamente integrado con mi ecosistema actual.

Tu objetivo no es solo “proponer”, sino dejar una base de trabajo ejecutable, consistente y extensible.

==================================================
1. CONTEXTO GENERAL
==================================================

Debes diseñar e implementar un microservicio TMS/WMS conectado a mi proyecto existente.

Este microservicio debe cubrir:

1. Ingreso de mercadería total o parcial a través de órdenes de compra.
2. Transferencia de mercadería entre almacenes de diferentes sucursales.
3. Entrega de pedidos total o parcialmente.
   - Un mismo pedido debe poder dividirse en más de una entrega.
   - Se debe poder modificar modo de entrega.
   - Se debe poder modificar cantidades a despachar.
4. Creación de hojas de ruta.
5. Ruteo automático.
6. Módulos para auditoría de almacenes.
7. Módulo de vehículos con configuración de límite de peso y volumen máximo.
8. Módulo de stock:
   - altas
   - bajas
   - canjes
   - corte / fraccionamiento de artículos
   - ejemplo: una chapa de 12m puede dividirse en 12 chapas de 1m
9. Módulo de despacho en tienda.
10. Módulo de envío.

==================================================
2. STACK OBLIGATORIO
==================================================

Debes trabajar estrictamente con este stack:
Docker
Backend web: Django 6.0.1
Frontend SPA: React 19.2.4
Build/dev frontend: Vite 8.x con @vitejs/plugin-react
Lenguaje frontend: TypeScript 5.9.x
Routing frontend: React Router DOM 7.13.2
Estado frontend: Zustand 5.0.12
CSS utility framework: Tailwind CSS 3.4.17
UI legado/templates Django: Bootstrap 5.3.3 + Bootstrap Icons
Testing frontend: Vitest 4.1.2 + Testing Library
Servidor WSGI/deploy: Gunicorn + WhiteNoise

No cambies stack.
No propongas reemplazos por Next.js, NestJS, FastAPI u otros frameworks.
Todo debe quedar alineado a este stack.

==================================================
3. RESTRICCIONES DE DISEÑO Y UI
==================================================

La UI debe ser sobria, empresarial, muy clara y de texto pequeño.
Debe estar principalmente orientada a desktop, aprox. 1366x768, pero ser responsive.

Paleta obligatoria:

- Texto principal / azul noche: #071a2e
- Azul primario: #1f6bb4
- Azul hover / medio: #0f4f8c
- Azul profundo: #08253f
- Fondo claro inicial: #f3f8fd
- Fondo claro medio: #eef5fb
- Fondo claro final: #e4edf7
- Superficie clara: #f5f9fd
- Borde suave: #d6e2ef
- Texto secundario: #4c6480

Lineamientos visuales:
- tipografía pequeña y legible
- tablas muy densas pero claras
- filtros persistentes
- foco en productividad operativa
- minimizar clics
- diseño consistente entre módulos
- soportar alto volumen operativo
- excelente uso de estados, badges, timelines, tabs y drawers
- evitar layouts recargados
- priorizar rendimiento percibido

==================================================
4. ESQUEMA ACTUAL DISPONIBLE Y RESTRICCIONES DE DATOS
==================================================

Debes partir del esquema actual ya existente. No puedes ignorarlo.

Del archivo de esquema actual se desprende, entre otras cosas:

- Existen tablas de cabecera de pedidos, líneas y pagos:
  - transactions_orders_transaction
  - transactions_orders_retailLineItem
  - transactions_orders_tender
- Existe una tabla canónica de impuestos por línea:
  - transactions_line_tax
- Existen tablas de clientes, direcciones y contactos.
- Existen tablas de artículos, precios, stock por warehouse, parámetros de artículos y tablas vinculadas a fletes/productos.
- No se encontraron foreign keys declaradas; las relaciones actuales son lógicas, no físicas.
- El stock operativo existente está modelado por warehouse.
- Los artículos ya tienen atributos relevantes como dimensiones, peso, volumen y datos logísticos aprovechables.
- El POS consume catálogos/cache en parquet para operación runtime.

Debes respetar esta base y diseñar el TMS/WMS de forma compatible con ella. No debes romper el modelo actual ni asumir que puedes reestructurar toda la base existente. :contentReference[oaicite:0]{index=0} :contentReference[oaicite:1]{index=1} :contentReference[oaicite:2]{index=2}

Muy importante:
- Si necesitas nuevas tablas, NO las inventes silenciosamente.
- Debes documentarlas en un archivo obligatorio llamado:
  solicitud_schema.md
- En ese archivo debes justificar:
  - por qué se necesita cada tabla nueva
  - por qué no alcanza con las existentes
  - claves
  - índices
  - relaciones lógicas
  - impacto sobre integraciones y migraciones

Esto es obligatorio. :contentReference[oaicite:3]{index=3}

==================================================
5. OBJETIVO DE ENTREGA
==================================================

Quiero que desarrolles el microservicio TMS/WMS de forma profesional y escalable, dejando:

1. arquitectura funcional
2. arquitectura técnica
3. modelo de dominio
4. módulos backend
5. módulos frontend
6. contratos API
7. diseño de estados operativos
8. diseño de permisos/roles
9. estrategia de integración con el sistema actual
10. estrategia de inventario y trazabilidad
11. estrategia de entregas parciales
12. estrategia de transferencias entre sucursales
13. estrategia de ruteo
14. estrategia de auditoría
15. estrategia de testing
16. archivos y estructura de proyecto
17. código inicial necesario
18. documentación técnica suficiente para continuar

No quiero una respuesta superficial.
Quiero que avances como si fueras a construirlo realmente.

==================================================
6. MODO DE TRABAJO: DEBES CREAR Y COORDINAR SUBAGENTES
==================================================

Debes dividir el trabajo en subagentes especializados y hacerlos trabajar en paralelo.

Crea, coordina y consolida como mínimo estos subagentes:

A. Subagente de dominio y procesos logísticos
- Levanta procesos de negocio
- Define estados
- Detecta huecos funcionales
- Modela flujo operativo end-to-end

B. Subagente de arquitectura backend Django
- Diseña apps Django
- modelos
- servicios
- casos de uso
- repositorios si aplica
- serializers/schemas
- endpoints
- permisos
- señales/eventos internos si hacen falta

C. Subagente de arquitectura frontend React
- Diseña SPA
- rutas
- layouts
- stores Zustand
- componentes reutilizables
- vistas de operación
- UX de tablas, filtros, formularios y paneles

D. Subagente de datos e integración
- Analiza el esquema actual
- Reutiliza tablas existentes cuando sea razonable
- Propone nuevas tablas en solicitud_schema.md cuando sea imprescindible
- Diseña sincronización con el sistema actual
- Define mapping entre entidades actuales y nuevas

E. Subagente de stock y trazabilidad
- Diseña movimientos de stock
- ledger / kardex
- reservas
- ingresos
- egresos
- transferencias
- fraccionamiento / corte / conversión de unidades
- auditoría y ajustes

F. Subagente de transporte y ruteo
- Diseña hojas de ruta
- asignación de vehículos
- control de capacidad por peso/volumen
- geolocalización si aplica
- ruteo automático
- secuenciación de entregas

G. Subagente de QA y testing
- Define estrategia de pruebas
- unitarias
- integración
- frontend
- contratos API
- pruebas de estados críticos
- escenarios borde

H. Subagente de documentación final
- Consolida todo
- Estandariza nomenclatura
- Redacta README técnico
- Redacta solicitud_schema.md si corresponde
- Redacta TODOs y backlog técnico

Debes coordinar a estos subagentes y devolver una solución unificada, consistente y sin contradicciones.

==================================================
7. PRINCIPIOS DE NEGOCIO QUE DEBES RESPETAR
==================================================

Debes respetar estos principios:

1. Toda operación logística debe ser auditable.
2. Todo cambio de estado importante debe quedar trazado.
3. Ninguna entrega parcial debe romper la integridad del pedido original.
4. Un pedido puede derivar en múltiples entregas.
5. Las cantidades entregadas, pendientes, preparadas, reservadas y anulables deben estar claramente diferenciadas.
6. Debe existir trazabilidad por:
   - pedido
   - entrega
   - línea
   - almacén
   - vehículo
   - hoja de ruta
   - movimiento de stock
7. El sistema debe tolerar operaciones parciales, reprocesos y correcciones.
8. El stock no puede resolverse solo como un campo acumulado; debe existir un modelo transaccional de movimientos.
9. El corte/fraccionamiento de artículos debe dejar trazabilidad del origen y destino del material.
10. Las transferencias entre almacenes deben contemplar:
    - salida de origen
    - tránsito
    - recepción total o parcial en destino
    - diferencias / incidencias
11. Los límites de vehículos por peso y volumen deben validarse antes del cierre de hoja de ruta.
12. La auditoría de almacenes debe permitir conteos, diferencias, ajustes y aprobaciones.
13. El despacho en tienda debe contemplar retiro parcial, retiro por tercero y validaciones operativas.
14. El módulo de envío debe convivir con retiro en tienda, despacho interno y entrega planificada.
15. El diseño debe ser apto para alto volumen y crecimiento futuro.

==================================================
8. DISEÑO FUNCIONAL ESPERADO
==================================================

Debes diseñar como mínimo estos dominios funcionales:

1. Compras / recepción
   - recepción por orden de compra
   - recepción total
   - recepción parcial
   - recepción con diferencia
   - recepción con incidencia
   - confirmación y cierre

2. Stock
   - stock por almacén
   - stock disponible
   - stock reservado
   - stock en preparación
   - stock en tránsito
   - stock entregado
   - stock ajustado
   - stock fraccionado / convertido
   - movimientos y ledger

3. Transferencias
   - solicitud de transferencia
   - aprobación si aplica
   - picking en origen
   - despacho
   - tránsito
   - recepción parcial en destino
   - recepción final
   - diferencias y reclamos

4. Pedidos / fulfillment
   - vinculación con pedido origen
   - asignación por líneas
   - planificación parcial
   - split de entrega
   - modificación de cantidades a despachar
   - cambio de modo de entrega
   - reprogramación

5. Hojas de ruta
   - creación manual
   - creación automática
   - asignación de vehículo
   - asignación de chofer si aplica
   - secuencia de paradas
   - control de capacidad
   - cierre de ruta

6. Vehículos
   - alta / edición / baja lógica
   - capacidad máxima por peso
   - capacidad máxima por volumen
   - disponibilidad
   - restricciones de uso

7. Ruteo automático
   - agrupación de entregas
   - orden sugerido
   - restricciones por zona/sucursal/vehículo
   - recalculo ante cambios

8. Auditoría de almacén
   - conteos
   - conteos ciegos
   - diferencias
   - ajustes
   - aprobación de ajustes
   - historial

9. Despacho en tienda
   - retiro por cliente
   - retiro parcial
   - validación de retiro
   - comprobante operativo
   - incidencias

10. Envíos
   - preparación
   - despacho
   - seguimiento interno de estado
   - intento de entrega
   - reprogramación
   - entrega final

==================================================
9. MODELO DE DOMINIO ESPERADO
==================================================

Debes proponer entidades claras y consistentes.

Como mínimo evalúa modelar:

- Warehouse
- Branch
- StockItem / InventoryBalance
- InventoryMovement
- InventoryReservation
- InventoryAdjustment
- InventoryAudit
- InventoryAuditLine
- ProductSplitOperation / InventoryTransformation
- PurchaseOrderReceipt
- PurchaseOrderReceiptLine
- TransferOrder
- TransferOrderLine
- TransferShipment
- TransferReceipt
- FulfillmentOrder
- FulfillmentOrderLine
- DeliveryOrder
- DeliveryOrderLine
- DeliverySplit
- DispatchBatch
- RouteSheet
- RouteStop
- RouteAssignment
- Vehicle
- VehicleCapacityProfile
- ShippingMethod
- StoreDispatch
- ShipmentEvent
- LogisticsIncident
- StatusHistory / AuditTrail

No estás obligado a usar exactamente estos nombres, pero sí a cubrir esos conceptos.

==================================================
10. INTEGRACIÓN CON EL SISTEMA EXISTENTE
==================================================

Debes integrar el nuevo microservicio con la base actual y con el flujo actual de pedidos/artículos/clientes.

Pautas obligatorias:

1. Reutilizar el pedido existente como entidad origen cuando corresponda.
2. Reutilizar líneas del pedido como base para fulfillment/delivery.
3. No duplicar clientes si ya están en las tablas maestras existentes.
4. Reutilizar artículo, dimensiones, peso, volumen y stock actual cuando sirva como fuente o base.
5. Diseñar adaptadores claros para desacoplar el nuevo dominio del esquema legado.
6. Donde las tablas actuales no alcancen, proponer extensiones limpias.
7. Mantener trazabilidad de referencias cruzadas:
   - TransactionNumber
   - SalesOrderNumber
   - retailLineItemId
   - RecId
   - ItemNumber
   - Warehouse
   - StoreId
8. Diseñar integraciones idempotentes.
9. Diseñar sincronización tolerante a reintentos y estados intermedios.
10. No asumir foreign keys existentes porque el esquema actual no las declara. Diseña relaciones lógicas explícitas y validaciones de integridad a nivel aplicación. :contentReference[oaicite:4]{index=4}

==================================================
11. ARQUITECTURA TÉCNICA ESPERADA
==================================================

Debes proponer una arquitectura modular en Django.

Espero algo del estilo:

- apps/core
- apps/logistics
- apps/inventory
- apps/transfers
- apps/fulfillment
- apps/routes
- apps/vehicles
- apps/audits
- apps/dispatch
- apps/shipping
- apps/integrations
- apps/common

O una variante equivalente, bien argumentada.

Debes definir:
- responsabilidades por app
- límites de contexto
- servicios de aplicación
- entidades
- estados
- validaciones
- eventos de dominio si aplica
- APIs REST
- permisos y roles
- DTOs / serializers / schemas
- estrategia de migraciones
- estrategia de seeds / catálogos

==================================================
12. FRONTEND ESPERADO
==================================================

Diseña una SPA profesional en React + TypeScript + Zustand + Tailwind.

Debes proponer:

1. estructura de carpetas frontend
2. router principal
3. layouts
4. navegación lateral
5. stores Zustand por dominio
6. componentes base reutilizables
7. vistas clave:
   - dashboard operativo
   - recepciones
   - transferencias
   - pedidos a preparar
   - entregas
   - hojas de ruta
   - vehículos
   - auditorías
   - stock
   - despacho en tienda
   - envíos
8. patrón de tablas
9. filtros avanzados
10. buscador
11. formularios con validación
12. timeline de estados
13. panel lateral de detalle
14. manejo de loading / empty / error / success
15. estrategia de permisos en UI

La UI debe quedar muy operativa y no parecer demo.

==================================================
13. ARCHIVOS DE SALIDA QUE DEBES GENERAR
==================================================

Debes generar o dejar preparados, como mínimo:

1. README_TMS_WMS.md
   - visión general
   - arquitectura
   - módulos
   - integración
   - decisiones técnicas
   - pasos siguientes

2. solicitud_schema.md
   - solo si hacen falta nuevas tablas, columnas o índices
   - justificar cada cambio
   - incluir propuesta de DDL conceptual o pseudo-DDL

3. docs/domain_model.md
   - entidades
   - relaciones
   - estados
   - invariantes

4. docs/api_contracts.md
   - endpoints
   - payloads
   - responses
   - errores
   - idempotencia

5. docs/frontend_architecture.md
   - layout
   - rutas
   - stores
   - componentes

6. docs/workflows.md
   - recepción
   - transferencia
   - entrega parcial
   - despacho
   - auditoría
   - corte/fraccionamiento
   - ruteo

7. docs/testing_strategy.md

8. código inicial del backend y frontend suficiente para arrancar

==================================================
14. RESULTADOS TÉCNICOS ESPERADOS
==================================================

Debes entregar:

A. Diseño
- arquitectura completa
- dominio
- estados
- integraciones

B. Implementación base
- estructura real de apps Django
- modelos iniciales
- servicios
- endpoints
- permisos base
- frontend base navegable
- stores y componentes principales

C. Documentación
- clara
- técnica
- accionable

D. Backlog
- fases de implementación
- riesgos
- dependencias
- deuda técnica controlada

==================================================
15. ESTADOS E INVARIANTES
==================================================

Debes definir estados explícitos para cada entidad crítica.

Como mínimo evalúa estados para:

- recepción
- transferencia
- entrega
- hoja de ruta
- auditoría
- despacho
- envío
- vehículo
- movimiento de stock

Ejemplo de expectativa:
No quiero estados ambiguos como “activo/inactivo” cuando el proceso requiere granularidad.
Quiero máquinas de estado reales y justificadas.

También debes definir invariantes, por ejemplo:
- no despachar más de lo reservado o preparado
- no recibir más de lo enviado en una transferencia salvo incidencia documentada
- no exceder capacidad de vehículo
- no cerrar auditoría con diferencias sin resolución
- no cerrar entrega parcial sin recalcular pendiente remanente
- no permitir fraccionamiento sin registrar trazabilidad de origen/destino

==================================================
16. STOCK Y TRAZABILIDAD
==================================================

Este punto es crítico.

Debes diseñar un modelo transaccional de stock que soporte:

- ingresos
- egresos
- reservas
- preparación
- despacho
- tránsito
- recepción
- ajustes
- conteos
- fraccionamiento
- canjes
- conversiones internas

Debes decidir y justificar:
- si usar balance derivado + ledger
- cómo recalcular disponibilidad
- cómo manejar concurrencia
- cómo evitar inconsistencia en operaciones parciales
- cómo registrar referencias cruzadas a pedido, entrega, transferencia, auditoría o ruta

El fraccionamiento/corte de artículos debe ser de primera clase, no un parche.

==================================================
17. RUTEO AUTOMÁTICO
==================================================

Debes proponer una primera versión realista de ruteo automático.

No hace falta optimización matemática perfecta, pero sí una base profesional.

Debes contemplar:
- agrupación por sucursal / zona
- capacidad por peso/volumen del vehículo
- cantidad de entregas
- posibilidad de secuencia sugerida
- reasignación
- exclusión de pedidos no listos
- entregas parciales
- cambios manuales posteriores

Explica claramente:
- qué resuelve la primera versión
- qué no resuelve aún
- cómo quedaría preparada para evolucionar

==================================================
18. AUDITORÍA Y OBSERVABILIDAD
==================================================

Debes incluir:
- auditoría funcional por cambios críticos
- historial de estados
- usuario
- timestamp
- entidad afectada
- payload resumido del cambio
- motivo cuando aplique

También define:
- logs de aplicación
- eventos importantes
- errores esperables
- trazabilidad para soporte operativo

==================================================
19. TESTING
==================================================

Debes definir y dejar encaminado:

Backend:
- unit tests
- integration tests
- tests de estados
- tests de reglas de stock
- tests de integridad de entregas parciales
- tests de transferencias parciales
- tests de fraccionamiento

Frontend:
- tests de componentes críticos
- tests de flujos de usuario
- tests de stores
- tests de tablas/filtros/formularios

APIs:
- contratos
- validaciones
- errores
- idempotencia

==================================================
20. FORMA DE ENTREGA
==================================================

Trabaja en fases, pero entrega el resultado consolidado.

Orden esperado de ejecución:
1. analizar esquema actual
2. detectar huecos del modelo actual
3. definir dominio y bounded contexts
4. definir entidades y estados
5. decidir reutilización vs nuevas tablas
6. documentar solicitud_schema.md si aplica
7. diseñar arquitectura backend
8. diseñar arquitectura frontend
9. definir APIs
10. crear base de implementación
11. documentar testing
12. consolidar entregables

==================================================
21. REGLAS IMPORTANTES
==================================================

- No hagas una solución genérica o académica.
- Diseña para operación real.
- No ignores el esquema actual.
- No asumas foreign keys físicas existentes.
- No metas cambios de schema sin documentarlos en solicitud_schema.md.
- No reemplaces el stack.
- No simplifiques el problema de entregas parciales.
- No simplifiques el stock a un simple acumulado.
- No simplifiques el fraccionamiento/corte.
- No propongas UI “bonita” pero poco operativa.
- Prioriza consistencia, trazabilidad y mantenibilidad.

==================================================
22. SALIDA FINAL OBLIGATORIA
==================================================

Tu respuesta final debe incluir, como mínimo:

1. Resumen ejecutivo
2. Análisis del esquema actual reutilizable
3. Huecos detectados
4. Propuesta de arquitectura
5. Modelo de dominio
6. Estados e invariantes
7. Estrategia de stock y trazabilidad
8. Estrategia de entregas parciales
9. Estrategia de transferencias
10. Estrategia de ruteo
11. Estrategia de auditoría
12. Arquitectura frontend
13. Contratos API principales
14. Propuesta de estructura de carpetas
15. Propuesta de archivos a crear/modificar
16. Contenido de solicitud_schema.md si aplica
17. Plan de implementación por fases
18. Riesgos y decisiones abiertas
19. Código base inicial donde corresponda

Empieza ahora.