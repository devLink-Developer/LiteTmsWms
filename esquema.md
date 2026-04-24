# Esquema Litecore: pedidos y clientes

Fuente: PostgreSQL `litecore`, esquema `public`, consultado desde el contenedor `mypos_web`.

Convenciones:

- `!`: columna `NOT NULL`
- `?`: columna nullable
- `PK`: primary key
- `UQ`: unique key / unique index

## Parametros de conexion

La aplicacion toma la conexion Litecore desde variables de entorno y la configura en `DATABASES["litecore"]` de Django.

| Parametro Django | Variable de entorno | Valor actual observado |
|---|---|---|
| `ENGINE` | fijo en settings | `django.db.backends.postgresql` |
| `HOST` | `POSTGRES_DB_HOST` | `10.11.0.30` |
| `PORT` | `POSTGRES_DB_PORT` | `5433` |
| `NAME` | `POSTGRES_DB_NAME` | `litecore` |
| `USER` | `POSTGRES_DB_USER` | `litecore` |
| `PASSWORD` | `POSTGRES_DB_PASS` | usar variable de entorno, no versionar |

Ejemplo de cadena de conexion sin exponer password:

```text
postgresql://litecore:${POSTGRES_DB_PASS}@10.11.0.30:5433/litecore
```

## Relaciones logicas principales

No se encontraron foreign keys declaradas para estas tablas en `information_schema`. La aplicacion relaciona por claves logicas:

```text
transactions_orders_transaction."TransactionNumber" = transactions_orders_retailLineItem."TransactionNumber"
transactions_orders_transaction."TransactionNumber" = transactions_orders_tender."TransactionNumber"
transactions_orders_transaction."SalesOrderNumber" = transactions_orders_retailLineItem."SalesOrderNumber"
transactions_orders_transaction."SalesOrderNumber" = transactions_orders_tender."SalesOrderNumber"
transactions_orders_transaction."CustomerAccount" = Maestros_Clientes."CustomerAccount"
transactions_orders_transaction."InvoiceCustomerAccountNumber" = Maestros_Clientes."CustomerAccount"
transactions_orders_tender."CustAccount" = Maestros_Clientes."CustomerAccount"
Maestros_Clientes_Direcciones."CustomerAccountNumber" = Maestros_Clientes."CustomerAccount"
Maestros_Clientes_Contactos."CustomerAccount" = Maestros_Clientes."CustomerAccount"
```

## Pedidos

### Cabecera: `public.transactions_orders_transaction`

Primary key: `"transactionId"`.

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"transactionId"` | `varchar(100)` | ! |  | PK |
| 2 | `"Warehouse"` | `varchar(60)` | ! |  |  |
| 3 | `"InvoiceDate"` | `timestamp with time zone` | ! |  |  |
| 4 | `"InvoiceNumber"` | `varchar(60)` | ! |  |  |
| 5 | `"Terminal"` | `varchar(60)` | ! |  |  |
| 6 | `"TransactionNumber"` | `varchar(60)` | ! |  |  |
| 7 | `"CreatedDateTime"` | `timestamp with time zone` | ! |  |  |
| 8 | `"DocInvoiceIdOrig"` | `varchar(60)` | ! |  |  |
| 9 | `"DocTypeId"` | `varchar(60)` | ! |  |  |
| 10 | `"SalesOrderNumberOrig"` | `varchar(60)` | ! |  |  |
| 11 | `"CustomerWorker"` | `varchar(60)` | ! |  |  |
| 12 | `"SalesOrderName"` | `varchar(60)` | ! |  |  |
| 13 | `"InvoiceCustomerAccountNumber"` | `varchar(60)` | ! |  |  |
| 14 | `"SalesOrderNumber"` | `varchar(60)` | ! |  |  |
| 15 | `"DocAuthorizationCodeType"` | `integer` | ! |  |  |
| 16 | `"DocAuthorizationCode"` | `varchar(60)` | ! |  |  |
| 17 | `"CustomersOrderReference"` | `varchar(60)` | ! |  |  |
| 18 | `"FixedChargeAmount"` | `numeric(32,6)` | ! |  |  |
| 19 | `"InvoiceAddressStateId"` | `varchar(60)` | ! |  |  |
| 20 | `"InvoiceAddressCity"` | `varchar(60)` | ! |  |  |
| 21 | `"InvoiceAddressStreet"` | `varchar(250)` | ! |  |  |
| 22 | `"InvoiceAddressStreetNumber"` | `varchar(60)` | ! |  |  |
| 23 | `"TaxExemptNumber"` | `varchar(60)` | ! |  |  |
| 24 | `"ModifiedDateTime"` | `timestamp with time zone` | ! |  |  |
| 25 | `"OrderResponsiblePersonnelNumber"` | `varchar(60)` | ! |  |  |
| 26 | `"Currency"` | `varchar(60)` | ! |  |  |
| 27 | `"CustomerAccount"` | `varchar(60)` | ! |  |  |
| 28 | `"OrigReasonCodeOrig"` | `varchar(60)` | ! |  |  |
| 29 | `"InvoiceHeaderTaxAmount"` | `numeric(32,6)` | ! |  |  |
| 30 | `"SalesOrderType"` | `varchar(10)` | ! |  |  |
| 31 | `"OrderStatus"` | `varchar(20)` | ! |  |  |
| 32 | `"QuotationNumber"` | `varchar(60)` | ? |  |  |
| 33 | `"RecId"` | `uuid` | ! | `gen_random_uuid()` |  |
| 34 | `"Estado"` | `boolean` | ! |  |  |
| 35 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 36 | `"CreadoPor"` | `varchar(100)` | ! |  |  |
| 37 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 38 | `"ModificadoPor"` | `varchar(100)` | ! |  |  |
| 39 | `"RowVersion"` | `bytea` | ? |  |  |
| 40 | `"InvoiceAddressCountryRegionIsoCode"` | `varchar(60)` | ? |  |  |
| 41 | `"InvoiceAddressZipCode"` | `varchar(60)` | ? |  |  |
| 42 | `"LegacySent"` | `boolean` | ! |  |  |
| 43 | `"LegacySentAt"` | `timestamp with time zone` | ? |  |  |
| 44 | `"StoreId"` | `varchar(60)` | ? |  |  |
| 45 | `"OrderTakerPersonnelNumber"` | `varchar(60)` | ? |  |  |
| 46 | `"LockOrder"` | `boolean` | ! |  |  |
| 47 | `"SalesSegmentId"` | `varchar(60)` | ? |  |  |
| 48 | `"SalesSubsegmentId"` | `varchar(60)` | ? |  |  |
| 49 | `"IsEmployed"` | `boolean` | ! |  |  |
| 50 | `"FreightPaymentStatus"` | `varchar(60)` | ? |  |  |
| 51 | `"VATConditionId"` | `varchar(60)` | ? |  |  |
| 52 | `"TaxPCGrossIncAgreeType"` | `varchar(60)` | ? |  |  |
| 53 | `"TaxFiscalIdentificationId"` | `varchar(60)` | ? |  |  |
| 54 | `"TurnoId"` | `varchar(60)` | ? |  |  |
| 55 | `"LogisticsSent"` | `boolean` | ? |  |  |
| 56 | `"LogisticsSentAt"` | `timestamp with time zone` | ? |  |  |
| 57 | `"Origin"` | `varchar(60)` | ? |  |  |

Indices:

- `transactions_orders_transaction_pkey`: unique btree (`"transactionId"`)
- `"transactions_orders_transaction_RecId_86df922a"`: btree (`"RecId"`)

### Lineas: `public."transactions_orders_retailLineItem"`

Primary key: `"retailLineItemId"`.

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"retailLineItemId"` | `bigint` | ! |  | PK |
| 2 | `"Warehouse"` | `varchar(60)` | ! |  |  |
| 3 | `"CreatedDateTime"` | `timestamp with time zone` | ! |  |  |
| 4 | `"ModifiedDateTime"` | `timestamp with time zone` | ! |  |  |
| 5 | `"InvoiceNumber"` | `varchar(60)` | ! |  |  |
| 6 | `"Terminal"` | `varchar(60)` | ! |  |  |
| 7 | `"TransactionNumber"` | `varchar(60)` | ! |  |  |
| 8 | `"ExternalItemNumber"` | `varchar(60)` | ! |  |  |
| 9 | `"DocTypeId"` | `varchar(60)` | ! |  |  |
| 10 | `"SalesOrderOriginCode"` | `varchar(60)` | ! |  |  |
| 11 | `"InventTransIdReturn"` | `varchar(60)` | ! |  |  |
| 12 | `"InventoryLotIdAnu"` | `varchar(60)` | ! |  |  |
| 13 | `"InvoiceDate"` | `timestamp with time zone` | ! |  |  |
| 14 | `"CustomersOrderReference"` | `varchar(60)` | ! |  |  |
| 15 | `"DeliveryAddressCity"` | `varchar(60)` | ! |  |  |
| 16 | `"DeliveryAddressZipCode"` | `varchar(60)` | ! |  |  |
| 17 | `"DeliveryAddressStreet"` | `varchar(250)` | ! |  |  |
| 18 | `"DeliveryAddressStreetNumber"` | `varchar(60)` | ! |  |  |
| 19 | `"DeliveryAddressLocationId"` | `varchar(60)` | ! |  |  |
| 20 | `"InventoryLotId"` | `varchar(60)` | ! |  |  |
| 21 | `"RequestedShippingDate"` | `timestamp with time zone` | ! |  |  |
| 22 | `"ShippingWarehouseId"` | `varchar(60)` | ! |  |  |
| 23 | `"FulfillmentStoreId"` | `varchar(60)` | ! |  |  |
| 24 | `"SalesOrderLineRecId"` | `bigint` | ! |  |  |
| 25 | `"DeliveryAddressCountryRegionIsoCode"` | `varchar(60)` | ! |  |  |
| 26 | `"DeliveryAddressStateId"` | `varchar(60)` | ! |  |  |
| 27 | `"SalesPrice"` | `numeric(32,6)` | ! |  |  |
| 28 | `"Iva10"` | `numeric(32,6)` | ! |  |  |
| 29 | `"Iva21"` | `numeric(32,6)` | ! |  |  |
| 30 | `"Iibb"` | `numeric(32,6)` | ! |  |  |
| 31 | `"LineDiscountAmount"` | `numeric(32,6)` | ! |  |  |
| 32 | `"DeliveryModeCode"` | `varchar(60)` | ! |  |  |
| 33 | `"LineNumber"` | `numeric(32,16)` | ! |  |  |
| 34 | `"ItemNumber"` | `varchar(60)` | ! |  |  |
| 35 | `"ItemNumberOrig"` | `varchar(60)` | ! |  |  |
| 36 | `"OrderedSalesQuantity"` | `numeric(32,6)` | ! |  |  |
| 37 | `"SalesUnitSymbol"` | `varchar(60)` | ! |  |  |
| 38 | `"LineAmount"` | `numeric(32,6)` | ! |  |  |
| 39 | `"SalesOrderType"` | `varchar(10)` | ! |  |  |
| 40 | `"OrderStatus"` | `varchar(20)` | ! |  |  |
| 41 | `"RecId"` | `uuid` | ! | `gen_random_uuid()` |  |
| 42 | `"Estado"` | `boolean` | ! |  |  |
| 43 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 44 | `"CreadoPor"` | `varchar(100)` | ! |  |  |
| 45 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 46 | `"ModificadoPor"` | `varchar(100)` | ! |  |  |
| 47 | `"RowVersion"` | `bytea` | ? |  |  |
| 48 | `"CostPrice"` | `numeric(32,6)` | ! |  |  |
| 49 | `"ManualDiscountAmount"` | `numeric(32,6)` | ! |  |  |
| 50 | `"ManualDiscountAmountResponsible"` | `varchar(60)` | ? |  |  |
| 51 | `"CommercialDiscountPercent"` | `numeric(5,2)` | ! |  |  |
| 52 | `"CommercialDiscountPromoName"` | `varchar(120)` | ? |  |  |
| 53 | `"CommercialDiscountPromoNumber"` | `varchar(60)` | ? |  |  |
| 54 | `"FinancialDiscountPercent"` | `numeric(5,2)` | ! |  |  |
| 55 | `"FinancialDiscountPromoName"` | `varchar(120)` | ? |  |  |
| 56 | `"FinancialDiscountPromoNumber"` | `varchar(60)` | ? |  |  |
| 57 | `"SalesOrderNumber"` | `varchar(60)` | ? |  |  |
| 58 | `"LockOrderLines"` | `boolean` | ! |  |  |
| 59 | `"DeliveryAddressLongitude"` | `numeric(18,8)` | ? |  |  |
| 60 | `"DeliveryAddressLatitude"` | `numeric(18,8)` | ? |  |  |
| 61 | `"SalesQuantityDelivered"` | `numeric(32,6)` | ? |  |  |
| 62 | `"DeliveryAddressDescription"` | `varchar(250)` | ? |  |  |
| 63 | `"RemainSalesPhysical"` | `numeric(32,6)` | ? |  |  |
| 64 | `"LineDeliveryDate"` | `timestamp with time zone` | ? |  |  |
| 65 | `"RescheduledDeliveryDate"` | `timestamp with time zone` | ? |  |  |
| 66 | `"FinancialDiscountAmount"` | `numeric(32,6)` | ! |  |  |
| 67 | `"CommercialDiscountAmount"` | `numeric(32,6)` | ! |  |  |
| 68 | `"LineTotalDiscountPercent"` | `numeric(5,2)` | ! |  |  |
| 69 | `"LineDescription"` | `varchar(250)` | ? |  |  |
| 70 | `"MunicipalTaxAmount"` | `numeric(32,6)` | ? |  |  |
| 71 | `"MunicipalTaxCode"` | `varchar(60)` | ? |  |  |
| 72 | `"MunicipalTaxRate"` | `numeric(12,6)` | ? |  |  |
| 73 | `"ProvincialTaxAmount"` | `numeric(32,6)` | ? |  |  |
| 74 | `"ProvincialTaxCode"` | `varchar(60)` | ? |  |  |
| 75 | `"ProvincialTaxRate"` | `numeric(12,6)` | ? |  |  |
| 76 | `"Origin"` | `varchar(60)` | ? |  |  |
| 77 | `"ManualDiscountPercent"` | `numeric(5,2)` | ! |  |  |

Indices:

- `"transactions_orders_retailLineItem_pkey"`: unique btree (`"retailLineItemId"`)
- `"transactions_orders_retailLineItem_RecId_82e7df75"`: btree (`"RecId"`)

### Tender / pagos: `public.transactions_orders_tender`

Primary key: `"tenderId"`.

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"tenderId"` | `bigint` | ! |  | PK |
| 2 | `"Warehouse"` | `varchar(60)` | ! |  |  |
| 3 | `"CreatedDateTime"` | `timestamp with time zone` | ! |  |  |
| 4 | `"ModifiedDateTime"` | `timestamp with time zone` | ! |  |  |
| 5 | `"InvoiceNumber"` | `varchar(60)` | ! |  |  |
| 6 | `"Terminal"` | `varchar(60)` | ! |  |  |
| 7 | `"TransactionNumber"` | `varchar(60)` | ! |  |  |
| 8 | `"TransactionText"` | `varchar(512)` | ! |  |  |
| 9 | `"InvoiceDate"` | `timestamp with time zone` | ! |  |  |
| 10 | `"InstallmentCount"` | `integer` | ! |  |  |
| 11 | `"ExchangeRate"` | `numeric(32,16)` | ! |  |  |
| 12 | `"DocPaymCollectorBookId"` | `varchar(60)` | ! |  |  |
| 13 | `"CheckOwner"` | `integer` | ! |  |  |
| 14 | `"BankId"` | `varchar(60)` | ! |  |  |
| 15 | `"ClearingId"` | `varchar(60)` | ! |  |  |
| 16 | `"DocumentDate"` | `timestamp with time zone` | ! |  |  |
| 17 | `"DueDate"` | `timestamp with time zone` | ! |  |  |
| 18 | `"TyValueSeqNum"` | `varchar(60)` | ! |  |  |
| 19 | `"ComTyStatus"` | `integer` | ? |  |  |
| 20 | `"CustAccount"` | `varchar(60)` | ! |  |  |
| 21 | `"CardTypeId"` | `varchar(60)` | ! |  |  |
| 22 | `"LineNum"` | `numeric(32,16)` | ! |  |  |
| 23 | `"TenderTypeId"` | `varchar(60)` | ! |  |  |
| 24 | `"Amount"` | `numeric(32,6)` | ! |  |  |
| 25 | `"CurrencyCode"` | `varchar(60)` | ! |  |  |
| 26 | `"DocumentNum"` | `varchar(60)` | ! |  |  |
| 27 | `"WhCertNum"` | `varchar(60)` | ! |  |  |
| 28 | `"SalesOrderType"` | `varchar(10)` | ! |  |  |
| 29 | `"StoreId"` | `varchar(60)` | ? |  |  |
| 30 | `"RecId"` | `uuid` | ! | `gen_random_uuid()` |  |
| 31 | `"Estado"` | `boolean` | ! |  |  |
| 32 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 33 | `"CreadoPor"` | `varchar(100)` | ! |  |  |
| 34 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 35 | `"ModificadoPor"` | `varchar(100)` | ! |  |  |
| 36 | `"RowVersion"` | `bytea` | ? |  |  |
| 37 | `"SalesOrderNumber"` | `varchar(60)` | ? |  |  |
| 38 | `"OrderResponsiblePersonnelNumber"` | `varchar(60)` | ? |  |  |
| 39 | `"OrderTakerPersonnelNumber"` | `varchar(60)` | ? |  |  |
| 40 | `"TurnoId"` | `varchar(60)` | ? |  |  |
| 41 | `"SignerVATNum"` | `varchar(60)` | ? |  |  |
| 42 | `"CheckReceiver"` | `varchar(120)` | ? |  |  |
| 43 | `"ZipCode"` | `varchar(60)` | ? |  |  |
| 44 | `"FullAddress"` | `varchar(250)` | ? |  |  |
| 45 | `"PhoneNumber"` | `varchar(60)` | ? |  |  |
| 46 | `"Origin"` | `varchar(60)` | ? |  |  |

Indices:

- `transactions_orders_tender_pkey`: unique btree (`"tenderId"`)
- `"transactions_orders_tender_RecId_9dbc6407"`: btree (`"RecId"`)

### Impuestos por linea: `public.transactions_line_tax`

Tabla canonica relacionada con lineas de pedidos y presupuestos. Para pedidos, usar `TransactionType`, `TransactionNumber`, `SalesOrderNumber`, `InvoiceNumber`, `SourceLineId` y `LineNumber`.

Primary key: `"Id"`.

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"Estado"` | `boolean` | ! |  |  |
| 2 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 3 | `"CreadoPor"` | `varchar(100)` | ! |  |  |
| 4 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 5 | `"ModificadoPor"` | `varchar(100)` | ! |  |  |
| 6 | `"RowVersion"` | `bytea` | ? |  |  |
| 7 | `"RecId"` | `uuid` | ! |  |  |
| 8 | `"Id"` | `bigint` | ! |  | PK |
| 9 | `"TransactionType"` | `varchar(20)` | ! |  |  |
| 10 | `"SourceLineModel"` | `varchar(60)` | ? |  |  |
| 11 | `"SourceLineId"` | `bigint` | ? |  |  |
| 12 | `"SourceLineRecId"` | `uuid` | ? |  |  |
| 13 | `"TransactionNumber"` | `varchar(60)` | ! |  |  |
| 14 | `"SalesOrderNumber"` | `varchar(60)` | ? |  |  |
| 15 | `"SalesQuotationNumber"` | `varchar(60)` | ? |  |  |
| 16 | `"InvoiceNumber"` | `varchar(60)` | ? |  |  |
| 17 | `"LineNumber"` | `numeric(32,16)` | ? |  |  |
| 18 | `"ItemNumber"` | `varchar(60)` | ? |  |  |
| 19 | `"CustomerAccount"` | `varchar(60)` | ? |  |  |
| 20 | `"Currency"` | `varchar(10)` | ? |  |  |
| 21 | `"DeliveryAddressCity"` | `varchar(60)` | ? |  |  |
| 22 | `"DeliveryAddressStateId"` | `varchar(60)` | ? |  |  |
| 23 | `"DeliveryAddressLocationId"` | `varchar(60)` | ? |  |  |
| 24 | `"SalesTaxGroup"` | `varchar(20)` | ? |  |  |
| 25 | `"VATConditionId"` | `varchar(60)` | ? |  |  |
| 26 | `"GrossIncomeCondition"` | `varchar(20)` | ? |  |  |
| 27 | `"TaxLevel"` | `varchar(20)` | ! |  |  |
| 28 | `"TaxType"` | `varchar(20)` | ! |  |  |
| 29 | `"LocalTaxCode"` | `varchar(60)` | ? |  |  |
| 30 | `"LocalTaxDescription"` | `varchar(250)` | ? |  |  |
| 31 | `"ExternalTaxCode"` | `varchar(60)` | ? |  |  |
| 32 | `"ExternalTaxDescription"` | `varchar(250)` | ? |  |  |
| 33 | `"TaxJurisdictionName"` | `varchar(120)` | ? |  |  |
| 34 | `"TaxJurisdictionCode"` | `varchar(60)` | ? |  |  |
| 35 | `"TaxBaseAmount"` | `numeric(32,6)` | ? |  |  |
| 36 | `"TaxRate"` | `numeric(12,6)` | ? |  |  |
| 37 | `"TaxAmount"` | `numeric(32,6)` | ? |  |  |
| 38 | `"CalculationSource"` | `varchar(30)` | ! |  |  |
| 39 | `"ResolutionMethod"` | `varchar(30)` | ? |  |  |
| 40 | `"SourceReference"` | `varchar(120)` | ? |  |  |
| 41 | `"MappingVersion"` | `varchar(30)` | ? |  |  |
| 42 | `"Notes"` | `text` | ! |  |  |

Indices:

- `transactions_line_tax_pkey`: unique btree (`"Id"`)
- `"transactions_line_tax_RecId_9990f80c"`: btree (`"RecId"`)
- `txn_line_tax_ext_code_idx`: btree (`"ExternalTaxCode"`)
- `txn_line_tax_local_code_idx`: btree (`"LocalTaxCode"`)
- `txn_line_tax_so_line_idx`: btree (`"SalesOrderNumber"`, `"LineNumber"`)
- `txn_line_tax_source_id_idx`: btree (`"SourceLineId"`)
- `txn_line_tax_type_num_idx`: btree (`"TransactionType"`, `"TransactionNumber"`)

## Clientes

### Cliente: `public."Maestros_Clientes"`

Primary key: `"RecId"`.
Unique: `"CustomerAccount"`.

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"RecId"` | `uuid` | ! | `gen_random_uuid()` | PK |
| 2 | `"Estado"` | `boolean` | ! |  |  |
| 3 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 4 | `"CreadoPor"` | `varchar(100)` | ! |  |  |
| 5 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 6 | `"ModificadoPor"` | `varchar(100)` | ! |  |  |
| 7 | `"RowVersion"` | `bytea` | ? |  |  |
| 8 | `"CustomerAccount"` | `varchar(20)` | ! |  | UQ |
| 9 | `"PartyType"` | `varchar(12)` | ! |  |  |
| 10 | `"SalesTaxGroup"` | `varchar(20)` | ! |  |  |
| 11 | `"SalesSegmentId"` | `varchar(40)` | ! |  |  |
| 12 | `"SalesSubsegmentId"` | `varchar(40)` | ! |  |  |
| 13 | `"TaxExemptNumber"` | `varchar(30)` | ! |  |  |
| 14 | `"ReceiptEmail"` | `varchar(200)` | ! |  |  |
| 15 | `"CreditLimitIsMandatory"` | `boolean` | ! |  |  |
| 16 | `"OnHoldStatus"` | `varchar(10)` | ! |  |  |
| 17 | `"AddressBooks"` | `varchar(50)` | ! |  |  |
| 18 | `"SalesDistrict"` | `varchar(80)` | ! |  |  |
| 19 | `"Gender"` | `varchar(20)` | ! |  |  |
| 20 | `"OrganizationName"` | `varchar(200)` | ! |  |  |
| 21 | `"NameAlias"` | `varchar(200)` | ! |  |  |
| 22 | `"PersonFirstName"` | `varchar(120)` | ! |  |  |
| 23 | `"PersonLastName"` | `varchar(120)` | ! |  |  |
| 24 | `"CustomerGroupId"` | `varchar(30)` | ! |  |  |
| 25 | `"AxxTaxVATConditionId"` | `varchar(10)` | ! |  |  |
| 26 | `"AxxTaxGrossIncomeCondition"` | `varchar(20)` | ! |  |  |
| 27 | `"AxxTaxFiscalIdentificationType_TaxFiscalIdentificationId"` | `varchar(10)` | ! |  |  |
| 28 | `"AxxTaxPersonType"` | `varchar(20)` | ! |  |  |
| 29 | `"AxxTaxPCGrossIncAgreeType"` | `varchar(20)` | ! |  |  |
| 30 | `"CreditLimit"` | `numeric(14,2)` | ! |  |  |
| 31 | `"PrimaryContactPhone"` | `varchar(40)` | ! |  |  |
| 32 | `"Origin"` | `varchar(60)` | ! |  |  |
| 33 | `"Store"` | `varchar(60)` | ! |  |  |
| 34 | `"CustomerRelation"` | `varchar(60)` | ! |  |  |
| 35 | `"MainActivityId"` | `varchar(40)` | ! |  |  |
| 36 | `"BirthDate"` | `date` | ? |  |  |
| 37 | `"IsEmployee"` | `boolean` | ! |  |  |
| 38 | `"SalesCurrencyCode"` | `varchar(3)` | ! |  |  |
| 39 | `"IdExterno1"` | `varchar(100)` | ? |  |  |
| 40 | `"IdExterno2"` | `varchar(100)` | ? |  |  |
| 41 | `"IdExterno3"` | `varchar(100)` | ? |  |  |

Indices:

- `"Maestros_Clientes_pkey"`: unique btree (`"RecId"`)
- `"Maestros_Clientes_CustomerAccount_key"`: unique btree (`"CustomerAccount"`)
- `uq_customer_account`: unique btree (`"CustomerAccount"`)
- `"Maestros_Cl_est_acc_idx"`: btree (`"Estado"`, `"CustomerAccount"`)
- `"Maestros_Cl_est_mod_idx"`: btree (`"Estado"`, `"ModificadoEn"`)
- `"Maestros_Cl_tax_idx"`: btree (`"TaxExemptNumber"`)
- `"Maestros_Clientes_CustomerAccount_324c8231_like"`: btree (`"CustomerAccount" varchar_pattern_ops`)

### Direcciones de clientes: `public."Maestros_Clientes_Direcciones"`

Primary key: `"RecId"`.
Unique: (`"CustomerAccountNumber"`, `"AddressLocationId"`).

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"RecId"` | `uuid` | ! | `gen_random_uuid()` | PK |
| 2 | `"Estado"` | `boolean` | ! |  |  |
| 3 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 4 | `"CreadoPor"` | `varchar(300)` | ! |  |  |
| 5 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 6 | `"ModificadoPor"` | `varchar(300)` | ! |  |  |
| 7 | `"RowVersion"` | `bytea` | ? |  |  |
| 8 | `"dataAreaId"` | `varchar(300)` | ! |  |  |
| 9 | `"CustomerAccountNumber"` | `varchar(300)` | ! |  | UQ |
| 10 | `"CustomerLegalEntityId"` | `varchar(300)` | ! |  |  |
| 11 | `"AddressLocationId"` | `varchar(300)` | ! |  | UQ |
| 12 | `"Effective"` | `timestamp with time zone` | ? |  |  |
| 13 | `"IsPrivate"` | `varchar(300)` | ! |  |  |
| 14 | `"AddressBuilding"` | `varchar(300)` | ! |  |  |
| 15 | `"IsPrimary"` | `varchar(300)` | ! |  |  |
| 16 | `"AddressDistrictName"` | `varchar(300)` | ! |  |  |
| 17 | `"IsPrivatePostalAddress"` | `varchar(300)` | ! |  |  |
| 18 | `"IsRoleDelivery"` | `varchar(300)` | ! |  |  |
| 19 | `"AddressCountryRegionISOCode"` | `varchar(300)` | ! |  |  |
| 20 | `"IsPrimaryTaxRegistration"` | `varchar(300)` | ! |  |  |
| 21 | `"IsRoleBusiness"` | `varchar(300)` | ! |  |  |
| 22 | `"AddressDescription"` | `varchar(300)` | ! |  |  |
| 23 | `"AddressCountyId"` | `varchar(300)` | ! |  |  |
| 24 | `"IsPostalAddress"` | `varchar(300)` | ! |  |  |
| 25 | `"AddressStreetNumber"` | `varchar(300)` | ! |  |  |
| 26 | `"BuildingCompliment"` | `varchar(300)` | ! |  |  |
| 27 | `"AddressCity"` | `varchar(300)` | ! |  |  |
| 28 | `"AddressApartment"` | `varchar(300)` | ! |  |  |
| 29 | `"FormattedAddress"` | `text` | ! |  |  |
| 30 | `"IsLocationOwner"` | `varchar(300)` | ! |  |  |
| 31 | `"AddressLocationRoles"` | `varchar(300)` | ! |  |  |
| 32 | `"AddressPostBox"` | `varchar(300)` | ! |  |  |
| 33 | `"AddressDefaultRoles"` | `varchar(300)` | ! |  |  |
| 34 | `"AddressLongitude"` | `numeric(18,8)` | ! |  |  |
| 35 | `"AddressZipCode"` | `varchar(300)` | ! |  |  |
| 36 | `"AddressStreet"` | `varchar(300)` | ! |  |  |
| 37 | `"AddressLatitude"` | `numeric(18,8)` | ! |  |  |
| 38 | `"AddressCountryRegionId"` | `varchar(300)` | ! |  |  |
| 39 | `"AddressTimeZone"` | `varchar(300)` | ! |  |  |
| 40 | `"IsRoleHome"` | `varchar(300)` | ! |  |  |
| 41 | `"IsRoleInvoice"` | `varchar(300)` | ! |  |  |
| 42 | `"AttentionToAddressLine"` | `varchar(300)` | ! |  |  |
| 43 | `"Expiration"` | `timestamp with time zone` | ? |  |  |
| 44 | `"AddressState"` | `varchar(300)` | ! |  |  |
| 45 | `"ModifiedDateTime"` | `timestamp with time zone` | ? |  |  |
| 46 | `"AddressReference"` | `varchar(300)` | ! |  |  |
| 47 | `"Notes"` | `text` | ! |  |  |

Indices:

- `"Maestros_Clientes_Direcciones_pkey"`: unique btree (`"RecId"`)
- `"Maestros_Clientes_Direcc_CustomerAccountNumber_Ad_309327e2_uniq"`: unique btree (`"CustomerAccountNumber"`, `"AddressLocationId"`)
- `"Maestros_Cl_Custome_97c1da_idx"`: btree (`"CustomerAccountNumber"`)
- `"Maestros_Cl_Address_b07195_idx"`: btree (`"AddressLocationId"`)
- `"MCl_addr_est_acc_mod_idx"`: btree (`"Estado"`, `"CustomerAccountNumber"`, `"ModificadoEn"`)
- `"MCl_addr_est_loc_idx"`: btree (`"Estado"`, `"AddressLocationId"`)

### Contactos de clientes: `public."Maestros_Clientes_Contactos"`

Primary key: `"RecId"`.
Unique: (`"CustomerAccount"`, `"ElectronicAddressId"`).

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"RecId"` | `uuid` | ! | `gen_random_uuid()` | PK |
| 2 | `"Estado"` | `boolean` | ! |  |  |
| 3 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 4 | `"CreadoPor"` | `varchar(100)` | ! |  |  |
| 5 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 6 | `"ModificadoPor"` | `varchar(100)` | ! |  |  |
| 7 | `"RowVersion"` | `bytea` | ? |  |  |
| 8 | `"CustomerAccount"` | `varchar(20)` | ! |  | UQ |
| 9 | `"PartyNumber"` | `varchar(50)` | ! |  |  |
| 10 | `"ElectronicAddressId"` | `varchar(100)` | ! |  | UQ |
| 11 | `"IsInstantMessage"` | `boolean` | ! |  |  |
| 12 | `"IsMobilePhone"` | `boolean` | ! |  |  |
| 13 | `"CountryRegionCode"` | `varchar(10)` | ! |  |  |
| 14 | `"Purpose"` | `varchar(100)` | ! |  |  |
| 15 | `"Locator"` | `varchar(200)` | ! |  |  |
| 16 | `"LocatorExtension"` | `varchar(30)` | ! |  |  |
| 17 | `"LocationId"` | `varchar(60)` | ! |  |  |
| 18 | `"IsPrimary"` | `boolean` | ! |  |  |
| 19 | `"Description"` | `varchar(255)` | ! |  |  |
| 20 | `"Type"` | `varchar(10)` | ! |  |  |
| 21 | `"IsPrivate"` | `boolean` | ! |  |  |
| 22 | `"ModifiedDateTime"` | `timestamp with time zone` | ? |  |  |
| 23 | `"CreatedDateTime"` | `timestamp with time zone` | ? |  |  |

Indices:

- `"Maestros_Clientes_Contactos_pkey"`: unique btree (`"RecId"`)
- `uq_customer_contact_account_email`: unique btree (`"CustomerAccount"`, `"ElectronicAddressId"`)
- `"Maestros_Cl_Custome_07fb05_idx"`: btree (`"CustomerAccount"`)
- `"Maestros_Cl_PartyNu_12263d_idx"`: btree (`"PartyNumber"`)

## Articulos

Fuente: PostgreSQL `litecore`, esquema `public`. Ademas, el catalogo operativo que consume el POS se sirve desde archivos parquet `materiales_{STORE}.parquet` generados a partir de estos maestros/precios/stock.

No se encontraron foreign keys declaradas para estas tablas en `information_schema`. Las relaciones logicas principales son:

```text
maestros_materiales_sap."NumeroProducto" = maestros_materiales_textos."Product"
maestros_materiales_sap."NumeroProducto" = maestros_materiales_precios_costos."Material"
maestros_materiales_sap."NumeroProducto" = productos_precios_c_descuento_procesado."item"
maestros_materiales_sap."NumeroProducto" = maestros_articulos_parametros."NumeroProducto"
maestros_materiales_sap."NumeroProducto" = maestros_stock_warehousestockrecord."Codigo"
maestros_materiales_sap."NumeroProducto" = fletes_product_table."item_id"
transactions_orders_retailLineItem."ItemNumber" = maestros_materiales_sap."NumeroProducto"
```

### Maestro SAP: `public.maestros_materiales_sap`

Unique: `"NumeroProducto"`.

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"NumeroProducto"` | `varchar(60)` | ! |  | UQ |
| 2 | `"TipoProducto"` | `varchar(6)` | ? |  |  |
| 3 | `"TipoProductoDesc"` | `varchar(15)` | ? |  |  |
| 4 | `"CodigoCategoria"` | `varchar(13)` | ? |  |  |
| 5 | `"NombreCategoriaProducto"` | `varchar(30)` | ? |  |  |
| 6 | `"NombreProducto"` | `varchar(60)` | ? |  |  |
| 7 | `"GrupoCobertura"` | `varchar(27)` | ? |  |  |
| 8 | `"NumeroProductoAntiguo"` | `varchar(60)` | ? |  |  |
| 9 | `"UmBaseCodigo"` | `varchar(4)` | ? |  |  |
| 10 | `"UmBaseDesc"` | `varchar(4)` | ? |  |  |
| 11 | `"Largo"` | `numeric(13,3)` | ? |  |  |
| 12 | `"Ancho"` | `numeric(13,3)` | ? |  |  |
| 13 | `"Alto"` | `numeric(13,3)` | ? |  |  |
| 14 | `"UmDimensiones"` | `varchar(4)` | ? |  |  |
| 15 | `"PesoBruto"` | `numeric(13,3)` | ? |  |  |
| 16 | `"PesoNeto"` | `numeric(13,3)` | ? |  |  |
| 17 | `"UmPeso"` | `varchar(4)` | ? |  |  |
| 18 | `"Volumen"` | `numeric(13,3)` | ? |  |  |
| 19 | `"UmVolumen"` | `varchar(4)` | ? |  |  |
| 20 | `"Pais"` | `varchar(4)` | ? |  |  |
| 21 | `"CodigoImpuesto"` | `varchar(1)` | ? |  |  |
| 22 | `"DescripcionIVA"` | `varchar(13)` | ? |  |  |
| 23 | `"PorcentajeIVA"` | `numeric(3,1)` | ? |  |  |
| 24 | `"Multiplo"` | `double precision` | ? |  |  |
| 25 | `"CentroUsado"` | `varchar(6)` | ? |  |  |
| 26 | `"RN"` | `bigint` | ? |  |  |
| 27 | `"ProveedorId"` | `varchar(60)` | ? |  |  |
| 28 | `"ProveedorNombre"` | `varchar(60)` | ? |  |  |

Indices:

- `maestros_materiales_sap_numeroproducto_key`: unique btree (`"NumeroProducto"`)

### Textos de materiales: `public.maestros_materiales_textos`

Primary key: (`"Product"`, `"Language"`).

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"Product"` | `varchar(40)` | ! |  | PK |
| 2 | `"Language"` | `varchar(2)` | ! |  | PK |
| 3 | `"LongText"` | `text` | ? |  |  |
| 4 | `"FetchedAt"` | `timestamp with time zone` | ! | `now()` |  |

Indices:

- `maestros_materiales_textos_pkey`: unique btree (`"Product"`, `"Language"`)
- `ix_maestros_materiales_textos_product`: btree (`"Product"`)

### Precios y costos: `public.maestros_materiales_precios_costos`

Primary key: `"Id"`.

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"Id"` | `varchar(67)` | ! |  | PK |
| 2 | `"Material"` | `varchar(60)` | ? |  |  |
| 3 | `"Centro"` | `varchar(6)` | ? |  |  |
| 4 | `"CostoUnitario"` | `numeric(17,8)` | ? |  |  |
| 5 | `"MUPct"` | `numeric(16,6)` | ? |  |  |
| 6 | `"PrecioCalculado"` | `varchar(38)` | ? |  |  |
| 7 | `"PrecioValidoDesde"` | `varchar(12)` | ? |  |  |
| 8 | `"MUValidoDesde"` | `varchar(12)` | ? |  |  |
| 9 | `"PrecioValidoDesdeDate"` | `timestamp without time zone` | ? |  |  |
| 10 | `"MUValidoDesdeDate"` | `timestamp without time zone` | ? |  |  |
| 11 | `"PrecioValidoDesdeISO"` | `varchar(7500)` | ? |  |  |
| 12 | `"MUValidoDesdeISO"` | `varchar(7500)` | ? |  |  |
| 13 | `"RecencyDate"` | `timestamp without time zone` | ? |  |  |

Indices:

- `maestros_materiales_precios_costos_pkey`: unique btree (`"Id"`)
- `idx_precios_material_centro`: btree (`"Material"`, `"Centro"`)
- `idx_mm_costos_material_centro`: btree (`"Material"`, `"Centro"`) where `"PrecioCalculado" IS NOT NULL`

### Precios con descuento procesado: `public.productos_precios_c_descuento_procesado`

Primary key: `"id"`.

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"offerprice"` | `double precision` | ? |  |  |
| 2 | `"promonombre"` | `varchar(50)` | ? |  |  |
| 3 | `"preciofinal"` | `double precision` | ? |  |  |
| 4 | `"preciofinalconiva"` | `double precision` | ? |  |  |
| 5 | `"offerid"` | `varchar(50)` | ? |  |  |
| 6 | `"linenum"` | `double precision` | ? |  |  |
| 7 | `"offerdiscountmethod"` | `varchar(50)` | ? |  |  |
| 8 | `"offerdiscountpercentage"` | `double precision` | ? |  |  |
| 9 | `"storenumber"` | `varchar(50)` | ? |  |  |
| 10 | `"preciofinalcondesce"` | `double precision` | ? |  |  |
| 11 | `"validfrom"` | `varchar(50)` | ? |  |  |
| 12 | `"validto"` | `varchar(50)` | ? |  |  |
| 13 | `"status"` | `varchar(50)` | ? |  |  |
| 14 | `"pricegroupid"` | `varchar(50)` | ? |  |  |
| 15 | `"id"` | `varchar(120)` | ! |  | PK |
| 16 | `"item"` | `varchar(50)` | ? |  |  |
| 17 | `"price"` | `numeric(18,2)` | ? |  |  |
| 18 | `"pricegroup"` | `varchar(50)` | ? |  |  |
| 19 | `"codigoax"` | `varchar(8)` | ? |  |  |
| 20 | `"descripcion"` | `char(40)` | ? |  |  |

Indices:

- `productos_precios_c_descuento_procesado_pk`: unique btree (`"id"`)
- `idx_ppcdp_item_store`: btree (`"item"`, `"storenumber"`)

### Stock por warehouse: `public.maestros_stock_warehousestockrecord`

Primary key: `"RecId"`.
Unique: (`"Warehouse_id"`, `"Codigo"`).

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"RecId"` | `uuid` | ! |  | PK |
| 2 | `"Estado"` | `boolean` | ! |  |  |
| 3 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 4 | `"CreadoPor"` | `varchar(100)` | ! |  |  |
| 5 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 6 | `"ModificadoPor"` | `varchar(100)` | ! |  |  |
| 7 | `"RowVersion"` | `bytea` | ? |  |  |
| 8 | `"SyncId"` | `uuid` | ! |  |  |
| 9 | `"ExternalReference"` | `varchar(100)` | ! |  |  |
| 10 | `"Codigo"` | `varchar(100)` | ! |  | UQ |
| 12 | `"FetchedAt"` | `timestamp with time zone` | ! |  |  |
| 13 | `"Source"` | `varchar(32)` | ! |  |  |
| 14 | `"Site_id"` | `uuid` | ! |  |  |
| 15 | `"Warehouse_id"` | `uuid` | ! |  | UQ |
| 16 | `"Comprometido"` | `varchar(100)` | ! |  |  |
| 17 | `"DisponibleEntrega"` | `varchar(100)` | ! |  |  |
| 18 | `"DisponibleVenta"` | `varchar(100)` | ! |  |  |
| 19 | `"FechaTransaccion"` | `varchar(100)` | ! |  |  |
| 20 | `"ProductoId"` | `varchar(100)` | ! |  |  |
| 21 | `"StockFisico"` | `varchar(100)` | ! |  |  |

Indices:

- `maestros_stock_warehousestockrecord_pkey`: unique btree (`"RecId"`)
- `uq_stock_warehouse_codigo`: unique btree (`"Warehouse_id"`, `"Codigo"`)
- `stock_wh_codigo_idx`: btree (`"Warehouse_id"`, `"Codigo"`)
- `stock_ext_ref_idx`: btree (`"ExternalReference"`)
- `stock_site_idx`: btree (`"Site_id"`)
- `stock_sync_idx`: btree (`"SyncId"`)
- `maestros_stock_warehousestockrecord_site_id_3cd0ecaf`: btree (`"Site_id"`)
- `maestros_stock_warehousestockrecord_warehouse_id_1c972941`: btree (`"Warehouse_id"`)

### Parametros de articulos POS: `public.maestros_articulos_parametros`

Primary key: `"RecId"`.
Unique: `"NumeroProducto"`.

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"RecId"` | `uuid` | ! |  | PK |
| 2 | `"Estado"` | `boolean` | ! |  |  |
| 3 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 4 | `"CreadoPor"` | `varchar(100)` | ! |  |  |
| 5 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 6 | `"ModificadoPor"` | `varchar(100)` | ! |  |  |
| 7 | `"RowVersion"` | `bytea` | ? |  |  |
| 8 | `"NumeroProducto"` | `varchar(60)` | ! |  | UQ |
| 9 | `"CodigoBarras"` | `varchar(64)` | ! |  |  |
| 10 | `"CodigoQR"` | `varchar(128)` | ! |  |  |
| 11 | `"ValeExcluido"` | `boolean` | ! |  |  |
| 12 | `"ProductoFlete"` | `boolean` | ! |  |  |
| 13 | `"Activo"` | `boolean` | ! |  |  |
| 14 | `"DescuentoManual"` | `boolean` | ! |  |  |
| 15 | `"DescuentoComercial"` | `boolean` | ! |  |  |
| 16 | `"DescuentoFinanciero"` | `boolean` | ! |  |  |
| 17 | `"Surtido"` | `varchar(100)` | ! |  |  |
| 18 | `"Comentarios"` | `text` | ! |  |  |
| 19 | `"HabilitadoPOS"` | `boolean` | ! |  |  |
| 20 | `"HabilitadoEcommerce"` | `boolean` | ! |  |  |
| 22 | `"Complementario"` | `boolean` | ! |  |  |

Indices:

- `maestros_articulos_parametros_pkey`: unique btree (`"RecId"`)
- `maestros_articulos_parametros_numero_producto_key`: unique btree (`"NumeroProducto"`)
- `ix_parametros_numero_producto`: btree (`"NumeroProducto"`)
- `idx_map_numero_activo`: btree (`"NumeroProducto"`) where `"Activo" = true`
- `maestros_articulos_parametros_numero_producto_c5cbbed9_like`: btree (`"NumeroProducto" varchar_pattern_ops`)

### Articulos complementarios: `public.maestros_articulos_complementarios`

Primary key: `"RecId"`.
Unique: (`"ArticuloNumeroProducto"`, `"ArticuloComplementarioNumeroProducto"`).

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"RecId"` | `uuid` | ! |  | PK |
| 2 | `"Estado"` | `boolean` | ! |  |  |
| 3 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 4 | `"CreadoPor"` | `varchar(100)` | ! |  |  |
| 5 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 6 | `"ModificadoPor"` | `varchar(100)` | ! |  |  |
| 7 | `"RowVersion"` | `bytea` | ? |  |  |
| 8 | `"Cantidad"` | `numeric(10,2)` | ! |  |  |
| 9 | `"ArticuloNumeroProducto"` | `varchar(60)` | ! |  | UQ |
| 10 | `"ArticuloComplementarioNumeroProducto"` | `varchar(60)` | ! |  | UQ |
| 11 | `"ArticuloComplementarioNumeroProductoAntiguo"` | `varchar(60)` | ! |  |  |
| 12 | `"ArticuloNumeroProductoAntiguo"` | `varchar(60)` | ! |  |  |
| 13 | `"GrupoComplementario"` | `varchar(100)` | ! |  |  |
| 14 | `"GrupoComplementarioId"` | `uuid` | ? |  |  |

Indices:

- `maestros_articulos_complementarios_pkey`: unique btree (`"RecId"`)
- `uq_articulo_complementario`: unique btree (`"ArticuloNumeroProducto"`, `"ArticuloComplementarioNumeroProducto"`)
- `"maestros_articulos_complem_ArticuloNumeroProducto_0b844aef"`: btree (`"ArticuloNumeroProducto"`)
- `"maestros_articulos_complem_ArticuloComplementarioNume_8a3fc39b"`: btree (`"ArticuloComplementarioNumeroProducto"`)
- `"maestros_articulos_compl_ArticuloNumeroProducto_0b844aef_like"`: btree (`"ArticuloNumeroProducto" varchar_pattern_ops`)
- `"maestros_articulos_compl_ArticuloComplementarioNu_8a3fc39b_like"`: btree (`"ArticuloComplementarioNumeroProducto" varchar_pattern_ops`)

### Complementarios por sucursal: `public.maestros_articulos_complementarios_sucursales`

Primary key: `"RecId"`.
Unique: (`"GrupoComplementarioId"`, `"Sucursal"`).

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"RecId"` | `uuid` | ! |  | PK |
| 2 | `"Estado"` | `boolean` | ! |  |  |
| 3 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 4 | `"CreadoPor"` | `varchar(100)` | ! |  |  |
| 5 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 6 | `"ModificadoPor"` | `varchar(100)` | ! |  |  |
| 7 | `"RowVersion"` | `bytea` | ? |  |  |
| 8 | `"GrupoComplementarioId"` | `uuid` | ! |  | UQ |
| 9 | `"Sucursal"` | `varchar(20)` | ! |  | UQ |

Indices:

- `maestros_articulos_complementarios_sucursales_pkey`: unique btree (`"RecId"`)
- `uq_grupo_complementario_sucursal`: unique btree (`"GrupoComplementarioId"`, `"Sucursal"`)

### Tipo AFIP de item: `public.maestros_configuraciones_afipitemtype`

Primary key: `"RecId"`.
Unique: `"Code"`.

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"RecId"` | `uuid` | ! |  | PK |
| 2 | `"Estado"` | `boolean` | ! |  |  |
| 3 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 4 | `"CreadoPor"` | `varchar(100)` | ! |  |  |
| 5 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 6 | `"ModificadoPor"` | `varchar(100)` | ! |  |  |
| 7 | `"RowVersion"` | `bytea` | ? |  |  |
| 8 | `"Code"` | `varchar(40)` | ! |  | UQ |
| 9 | `"Description"` | `varchar(120)` | ! |  |  |

Indices:

- `maestros_configuraciones_afipitemtype_pkey`: unique btree (`"RecId"`)
- `"maestros_configuraciones_afipitemtype_Code_key"`: unique btree (`"Code"`)
- `"maestros_configuraciones_afipitemtype_Code_f964dc50_like"`: btree (`"Code" varchar_pattern_ops`)

### Producto para fletes: `public.fletes_product_table`

Primary key: `"RecId"`.

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"RecId"` | `uuid` | ! |  | PK |
| 2 | `"Estado"` | `boolean` | ! |  |  |
| 3 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 4 | `"CreadoPor"` | `varchar(100)` | ! |  |  |
| 5 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 6 | `"ModificadoPor"` | `varchar(100)` | ! |  |  |
| 7 | `"RowVersion"` | `bytea` | ? |  |  |
| 8 | `"item_id"` | `text` | ? |  |  |
| 9 | `"name"` | `text` | ? |  |  |
| 10 | `"height"` | `numeric(38,16)` | ? |  |  |
| 11 | `"width"` | `numeric(38,16)` | ? |  |  |
| 12 | `"net_weight"` | `numeric(38,16)` | ? |  |  |
| 13 | `"tara_weight"` | `numeric(38,16)` | ? |  |  |
| 14 | `"depth"` | `numeric(38,16)` | ? |  |  |
| 15 | `"unit_volume"` | `numeric(38,16)` | ? |  |  |
| 16 | `"density"` | `numeric(38,16)` | ? |  |  |
| 17 | `"gross_depth"` | `numeric(38,16)` | ? |  |  |
| 18 | `"gross_width"` | `numeric(38,16)` | ? |  |  |
| 19 | `"gross_height"` | `numeric(38,16)` | ? |  |  |
| 20 | `"data_area_id"` | `text` | ? |  |  |
| 21 | `"tax_packaging_qty"` | `numeric(38,16)` | ? |  |  |
| 22 | `"mssql_system_uniquifier"` | `bigint` | ? |  |  |

Indices:

- `fletes_product_table_pkey`: unique btree (`"RecId"`)
- `fletes_product_item_idx`: btree (`"item_id"`)

### Configuracion de venta por item para fletes: `public.fletes_invent_item_sales_setup`

Primary key: `"RecId"`.

| # | Columna | Tipo | Null | Default | Clave |
|---:|---|---|---|---|---|
| 1 | `"RecId"` | `uuid` | ! |  | PK |
| 2 | `"Estado"` | `boolean` | ! |  |  |
| 3 | `"CreadoEn"` | `timestamp with time zone` | ! |  |  |
| 4 | `"CreadoPor"` | `varchar(100)` | ! |  |  |
| 5 | `"ModificadoEn"` | `timestamp with time zone` | ! |  |  |
| 6 | `"ModificadoPor"` | `varchar(100)` | ! |  |  |
| 7 | `"RowVersion"` | `bytea` | ? |  |  |
| 8 | `"item_id"` | `text` | ? |  |  |
| 9 | `"delivery_date_control_type"` | `integer` | ? |  |  |
| 10 | `"highest_qty"` | `numeric(38,16)` | ? |  |  |
| 11 | `"lead_time"` | `integer` | ? |  |  |
| 12 | `"lowest_qty"` | `numeric(38,16)` | ? |  |  |
| 13 | `"multiple_qty"` | `numeric(38,16)` | ? |  |  |
| 14 | `"mssql_system_uniquifier"` | `bigint` | ? |  |  |

Indices:

- `fletes_invent_item_sales_setup_pkey`: unique btree (`"RecId"`)

## Cache operativo de articulos en parquet

El endpoint de catalogo `/api/productos` carga archivos `materiales_{STORE}.parquet` desde `SERVICES_CACHE_DIR` / `CACHE_DIR`. Estos archivos son la fuente runtime del POS para busqueda, precios finales, IVA, costo y disponibilidad resumida por tienda.

### Catalogo por tienda: `materiales_{STORE}.parquet`

Ejemplo consultado: `/srv/data/parquet/materiales_PS003MT.parquet`, 11.376 filas.

| # | Columna | Tipo |
|---:|---|---|
| 1 | `numero_producto` | `string` |
| 2 | `codigo_sap` | `string` |
| 3 | `item_id_sap` | `string` |
| 4 | `categoria_producto` | `string` |
| 5 | `nombre_producto` | `string` |
| 6 | `nombre_largo` | `string` |
| 7 | `grupo_cobertura` | `string` |
| 8 | `unidad_medida` | `string` |
| 9 | `unidad_medida_codigo` | `string` |
| 10 | `unidad_medida_desc` | `string` |
| 11 | `tipo` | `string` |
| 12 | `codigo_categoria` | `string` |
| 13 | `largo` | `double` |
| 14 | `ancho` | `double` |
| 15 | `alto` | `double` |
| 16 | `dimensiones` | `string` |
| 17 | `peso` | `double` |
| 18 | `um_peso` | `string` |
| 19 | `volumen` | `double` |
| 20 | `um_volumen` | `string` |
| 21 | `descripcion_iva` | `string` |
| 22 | `porcentaje_iva` | `double` |
| 23 | `multiplo` | `double` |
| 24 | `proveedor` | `string` |
| 25 | `precio_base` | `double` |
| 26 | `costo_unitario` | `double` |
| 27 | `precio_base_con_iva` | `double` |
| 28 | `importe_iva` | `double` |
| 29 | `store_number` | `string` |
| 30 | `store_name` | `string` |
| 31 | `promo_nombre` | `string` |
| 32 | `promonumber` | `string` |
| 33 | `promo_descuento_pct` | `double` |
| 34 | `metodo_descuento_pct` | `double` |
| 35 | `precio_con_iva_desc_promo` | `double` |
| 36 | `importe_desc_promo` | `double` |
| 37 | `precio_con_iva_desc_promo_y_financiero` | `double` |
| 38 | `total_disponible_entrega` | `double` |
| 39 | `signo` | `string` |

### Productos cache general: `productos_cache.parquet`

Ejemplo consultado: `/srv/data/parquet/productos_cache.parquet`, 460.458 filas.

| # | Columna | Tipo |
|---:|---|---|
| 1 | `numero_producto` | `string` |
| 2 | `categoria_producto` | `string` |
| 3 | `nombre_producto` | `string` |
| 4 | `grupo_cobertura` | `string` |
| 5 | `unidad_medida` | `string` |
| 6 | `precio_final_con_iva` | `double` |
| 7 | `precio_final_con_descuento` | `double` |
| 8 | `store_number` | `string` |
| 9 | `promo_nombre` | `string` |
| 10 | `descuento` | `double` |
| 11 | `total_disponible_venta` | `double` |
| 12 | `signo` | `string` |
| 13 | `multiplo` | `double` |

### Stock cache: `stock_cache.parquet`

Ejemplo consultado: `/srv/data/parquet/stock_cache.parquet`, 200.109 filas.

| # | Columna | Tipo |
|---:|---|---|
| 1 | `codigo` | `string` |
| 2 | `almacen_365` | `string` |
| 3 | `stock_fisico` | `double` |
| 4 | `disponible_venta` | `double` |
| 5 | `disponible_entrega` | `double` |
| 6 | `comprometido` | `double` |

### Atributos cache: `atributos_cache.parquet`

Ejemplo consultado: `/srv/data/parquet/atributos_cache.parquet`, 191.110 filas.

| # | Columna | Tipo |
|---:|---|---|
| 1 | `codigo` | `string` |
| 2 | `nombre` | `string` |
| 3 | `atributo` | `string` |
| 4 | `valor` | `string` |
