from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import CheckersView, LoginView, MeView, RolePermissionView, UserViewSet
from apps.audit.views import AuditLogView
from apps.catalog.views import ProductViewSet
from apps.checking.views import (
    PdaBarcodesView, PdaConfigView, PdaEventsView, PdaFinishCheckView, PdaFinishView, PdaOrdersView, PdaOrderView,
    ReasonViewSet,
)
from apps.orders.views import ImportViewSet, OrderViewSet
from apps.reports.views import CheckersReport, OperationsReport, OverviewReport, PickersReport, PickingReport, ReasonsReport

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("reasons", ReasonViewSet, basename="reason")
router.register("imports", ImportViewSet, basename="import")
router.register("orders", OrderViewSet, basename="order")
router.register("products", ProductViewSet, basename="product")

pda = [
    path("config/", PdaConfigView.as_view()),
    path("orders/", PdaOrdersView.as_view()),
    path("orders/<int:order_id>/", PdaOrderView.as_view()),
    path("orders/<int:order_id>/events/", PdaEventsView.as_view()),
    path("orders/<int:order_id>/finish/", PdaFinishView.as_view()),
    path("orders/<int:order_id>/finish-check/", PdaFinishCheckView.as_view()),
    path("barcodes/", PdaBarcodesView.as_view()),
]

urlpatterns = [
    path("auth/login/", LoginView.as_view()),
    path("auth/refresh/", TokenRefreshView.as_view()),
    path("auth/me/", MeView.as_view()),
    path("role-permissions/", RolePermissionView.as_view()),
    path("checkers/", CheckersView.as_view()),
    path("audit/", AuditLogView.as_view()),
    path("pda/", include(pda)),
    path("reports/overview/", OverviewReport.as_view()),
    path("reports/checkers/", CheckersReport.as_view()),
    path("reports/pickers/", PickersReport.as_view()),
    path("reports/reasons/", ReasonsReport.as_view()),
    path("reports/picking/", PickingReport.as_view()),
    path("reports/operations/", OperationsReport.as_view()),
    path("", include(router.urls)),
]
