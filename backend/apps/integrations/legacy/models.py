from __future__ import annotations

from django.db import models


class LegacyOrder(models.Model):
    transaction_id = models.CharField(db_column="transactionId", max_length=100, primary_key=True)
    warehouse = models.CharField(db_column="Warehouse", max_length=60)
    invoice_date = models.DateTimeField(db_column="InvoiceDate")
    invoice_number = models.CharField(db_column="InvoiceNumber", max_length=80)
    transaction_number = models.CharField(db_column="TransactionNumber", max_length=60)
    sales_order_number = models.CharField(db_column="SalesOrderNumber", max_length=60)
    sales_order_name = models.CharField(db_column="SalesOrderName", max_length=200)
    customer_account = models.CharField(db_column="CustomerAccount", max_length=60)
    invoice_customer_account_number = models.CharField(
        db_column="InvoiceCustomerAccountNumber",
        max_length=60,
    )
    order_status = models.CharField(db_column="OrderStatus", max_length=20)
    store_id = models.CharField(db_column="StoreId", max_length=60, blank=True, null=True)
    rec_id = models.UUIDField(db_column="RecId")
    created_datetime = models.DateTimeField(db_column="CreatedDateTime")
    modified_datetime = models.DateTimeField(db_column="ModifiedDateTime")
    logistics_sent = models.BooleanField(db_column="LogisticsSent", blank=True, null=True)
    logistics_sent_at = models.DateTimeField(db_column="LogisticsSentAt", blank=True, null=True)
    origin = models.CharField(db_column="Origin", max_length=80, blank=True, null=True)

    class Meta:
        managed = False
        db_table = "transactions_orders_transaction"

    def __str__(self) -> str:
        return self.sales_order_number or self.transaction_number


class LegacyOrderLine(models.Model):
    retail_line_item_id = models.BigIntegerField(db_column="retailLineItemId", primary_key=True)
    warehouse = models.CharField(db_column="Warehouse", max_length=60)
    transaction_number = models.CharField(db_column="TransactionNumber", max_length=60)
    sales_order_number = models.CharField(db_column="SalesOrderNumber", max_length=60, blank=True, null=True)
    sales_order_line_rec_id = models.BigIntegerField(db_column="SalesOrderLineRecId")
    line_number = models.DecimalField(db_column="LineNumber", max_digits=32, decimal_places=16)
    item_number = models.CharField(db_column="ItemNumber", max_length=60)
    ordered_sales_quantity = models.DecimalField(
        db_column="OrderedSalesQuantity",
        max_digits=32,
        decimal_places=6,
    )
    sales_quantity_delivered = models.DecimalField(
        db_column="SalesQuantityDelivered",
        max_digits=32,
        decimal_places=6,
        blank=True,
        null=True,
    )
    remain_sales_physical = models.DecimalField(
        db_column="RemainSalesPhysical",
        max_digits=32,
        decimal_places=6,
        blank=True,
        null=True,
    )
    sales_unit_symbol = models.CharField(db_column="SalesUnitSymbol", max_length=60)
    delivery_mode_code = models.CharField(db_column="DeliveryModeCode", max_length=60)
    shipping_warehouse_id = models.CharField(db_column="ShippingWarehouseId", max_length=60)
    fulfillment_store_id = models.CharField(db_column="FulfillmentStoreId", max_length=60)
    requested_shipping_date = models.DateTimeField(db_column="RequestedShippingDate")
    delivery_address_state_id = models.CharField(db_column="DeliveryAddressStateId", max_length=60)
    delivery_address_city = models.CharField(db_column="DeliveryAddressCity", max_length=60)
    delivery_address_street = models.CharField(db_column="DeliveryAddressStreet", max_length=250)
    delivery_address_street_number = models.CharField(db_column="DeliveryAddressStreetNumber", max_length=60)
    delivery_address_zip_code = models.CharField(db_column="DeliveryAddressZipCode", max_length=60)
    delivery_address_description = models.CharField(
        db_column="DeliveryAddressDescription",
        max_length=250,
        blank=True,
        null=True,
    )
    delivery_address_latitude = models.DecimalField(
        db_column="DeliveryAddressLatitude",
        max_digits=18,
        decimal_places=8,
        blank=True,
        null=True,
    )
    delivery_address_longitude = models.DecimalField(
        db_column="DeliveryAddressLongitude",
        max_digits=18,
        decimal_places=8,
        blank=True,
        null=True,
    )
    rec_id = models.UUIDField(db_column="RecId")
    order_status = models.CharField(db_column="OrderStatus", max_length=20)
    line_description = models.CharField(db_column="LineDescription", max_length=250, blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"transactions_orders_retailLineItem"'

    def __str__(self) -> str:
        return f"{self.sales_order_number}:{self.line_number}"


class LegacyOrderInvoice(models.Model):
    invoice_id = models.CharField(db_column="InvoiceId", max_length=120, primary_key=True)
    idempotency_key = models.CharField(db_column="IdempotencyKey", max_length=200)
    estado = models.CharField(db_column="Estado", max_length=40)
    cae = models.CharField(db_column="Cae", max_length=80, blank=True, null=True)
    invoice_number = models.CharField(db_column="InvoiceNumber", max_length=80)
    transaction_number = models.CharField(db_column="TransactionNumber", max_length=60)
    sales_order_number = models.CharField(db_column="SalesOrderNumber", max_length=60)
    invoice_customer_account_number = models.CharField(db_column="InvoiceCustomerAccountNumber", max_length=60)
    invoice_customer_account_name = models.CharField(db_column="InvoiceCustomerAccountName", max_length=200)
    delivery_mode_code = models.CharField(db_column="DeliveryModeCode", max_length=60, blank=True, null=True)
    total_invoice_amount = models.DecimalField(
        db_column="TotalInvoiceAmount",
        max_digits=18,
        decimal_places=6,
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(db_column="CreatedAt")
    updated_at = models.DateTimeField(db_column="UpdatedAt")

    class Meta:
        managed = False
        db_table = "transactions_orders_transaction_invoices"


class LegacyCustomer(models.Model):
    rec_id = models.UUIDField(db_column="RecId", primary_key=True)
    customer_account = models.CharField(db_column="CustomerAccount", max_length=20, unique=True)
    organization_name = models.CharField(db_column="OrganizationName", max_length=200)
    person_first_name = models.CharField(db_column="PersonFirstName", max_length=120)
    person_last_name = models.CharField(db_column="PersonLastName", max_length=120)
    primary_contact_phone = models.CharField(db_column="PrimaryContactPhone", max_length=40)
    store = models.CharField(db_column="Store", max_length=60)
    estado = models.BooleanField(db_column="Estado")

    class Meta:
        managed = False
        db_table = '"Maestros_Clientes"'


class LegacyItem(models.Model):
    numero_producto = models.CharField(db_column="NumeroProducto", max_length=60, primary_key=True)
    nombre_producto = models.CharField(db_column="NombreProducto", max_length=60, blank=True, null=True)
    um_base_codigo = models.CharField(db_column="UmBaseCodigo", max_length=4, blank=True, null=True)
    largo = models.DecimalField(db_column="Largo", max_digits=13, decimal_places=3, blank=True, null=True)
    ancho = models.DecimalField(db_column="Ancho", max_digits=13, decimal_places=3, blank=True, null=True)
    alto = models.DecimalField(db_column="Alto", max_digits=13, decimal_places=3, blank=True, null=True)
    peso_bruto = models.DecimalField(db_column="PesoBruto", max_digits=13, decimal_places=3, blank=True, null=True)
    volumen = models.DecimalField(db_column="Volumen", max_digits=13, decimal_places=3, blank=True, null=True)
    multiplo = models.FloatField(db_column="Multiplo", blank=True, null=True)

    class Meta:
        managed = False
        db_table = "maestros_materiales_sap"


class LegacyWarehouseStock(models.Model):
    rec_id = models.UUIDField(db_column="RecId", primary_key=True)
    warehouse_id = models.UUIDField(db_column="Warehouse_id")
    site_id = models.UUIDField(db_column="Site_id")
    codigo = models.CharField(db_column="Codigo", max_length=100)
    stock_fisico = models.CharField(db_column="StockFisico", max_length=100)
    disponible_venta = models.CharField(db_column="DisponibleVenta", max_length=100)
    disponible_entrega = models.CharField(db_column="DisponibleEntrega", max_length=100)
    comprometido = models.CharField(db_column="Comprometido", max_length=100)
    fetched_at = models.DateTimeField(db_column="FetchedAt")

    class Meta:
        managed = False
        db_table = "maestros_stock_warehousestockrecord"
