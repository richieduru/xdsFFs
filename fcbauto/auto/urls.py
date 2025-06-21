from django.urls import path
from . import views

app_name = 'auto'  

urlpatterns=[
    path('', views.upload_file, name='upload'),  
    path('verify-split/', views.verify_split_decision, name='verify_split_decision'),
    
]
