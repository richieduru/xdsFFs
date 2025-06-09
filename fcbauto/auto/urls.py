from django.urls import path
from . import views

urlpatterns=[
    path('', views.upload_file, name='upload_file'),
    path('verify-split/', views.verify_split_decision, name='verify_split_decision'),
]
