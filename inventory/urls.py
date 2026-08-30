from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.browse, name="browse"),
    path("scan/", views.scan, name="scan"),
    path("go/", views.go, name="go"),
    path("jump/", views.jump_to_container, name="jump_to_container"),
    path("search/", views.parts_search, name="parts_search"),
    path("tagging/", views.tagging_list, name="tagging_list"),
    path("tagging/<int:pk>/update/", views.tagging_update, name="tagging_update"),
    path("api/locate/", views.api_locate_part, name="api_locate_part"),
    path("containers/<int:number>/", views.container_detail, name="container_detail"),
    path(
        "containers/<int:number>/register-barcode/",
        views.register_container_barcode,
        name="register_container_barcode",
    ),
    path("drawers/<int:pk>/", views.drawer_detail, name="drawer_detail"),
    path("drawers/<int:pk>/register-barcode/", views.register_drawer_barcode, name="register_drawer_barcode"),
    path("drawers/<int:pk>/locate-led/", views.locate_drawer_led, name="locate_drawer_led"),
    path("intake/", views.part_intake, name="part_intake"),
    path("parts/<int:pk>/", views.part_detail, name="part_detail"),
    path("parts/<int:pk>/add-stock/", views.add_stock_item, name="add_stock_item"),
    path("parts/<int:pk>/add-photo/", views.add_part_photo, name="add_part_photo"),
    path("stock/<int:pk>/update-quantity/", views.update_stock_quantity, name="update_stock_quantity"),
    path("stock/<int:pk>/delete/", views.delete_stock_item, name="delete_stock_item"),
    path("containers/<int:number>/delete/", views.delete_container, name="delete_container"),
    path("labels/", views.labels, name="labels"),
    path("labels/generate/", views.generate_and_print_labels, name="generate_labels"),
    path("labels/print/", views.print_labels, name="print_labels"),
    path("barcode/<str:code>.svg", views.barcode_svg, name="barcode_svg"),
    path("projects/", views.project_list, name="project_list"),
    path("projects/<int:pk>/", views.project_detail, name="project_detail"),
    path("projects/<int:pk>/build/", views.build_project, name="build_project"),
    path("reorder/", views.reorder, name="reorder"),
    path("export/", views.export_inventory, name="export_inventory"),
    path("reference/", views.reference_list, name="reference_list"),
    path("reference/resistor-calculator/", views.resistor_calculator, name="resistor_calculator"),
]
