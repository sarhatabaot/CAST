from django.urls import path
from . import views

app_name = 'FP'  # Namespacing for the app

urlpatterns = [
    path('last-fp/', views.force_photometry_view, name='forced_photometry'),
    path('fp-result/<int:request_id>/', views.fp_result_fragment, name='result_fragment'),
    path('download-fp-results/', views.download_fp_csv, name='download_fp_csv'),
]