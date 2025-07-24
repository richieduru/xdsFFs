from django.urls import path
from . import views

app_name = 'auto'  

urlpatterns=[
    path('', views.upload_file, name='upload'),  
    path('tasks/', views.task_dashboard, name='task_dashboard'),
    path('tasks/<str:task_id>/', views.task_status, name='task_detail'),
    path('tasks/<str:task_id>/cancel/', views.cancel_task, name='cancel_task'),
    path('tasks/<str:task_id>/retry/', views.retry_task, name='retry_task'),
    path('tasks/<str:task_id>/delete/', views.delete_task, name='delete_task'),
    path('verify-split/', views.verify_split_decision, name='verify_split_decision'),
    path('verify-split/<str:task_id>/', views.verify_split_decision, name='verify_split_task'),
    path('task-status/<str:task_id>/', views.task_status, name='task_status'),
    path('api/task-status/<str:task_id>/', views.task_status_api, name='task_status_api'),
    path('results/<str:task_id>/', views.display_results, name='display_results'),
]
