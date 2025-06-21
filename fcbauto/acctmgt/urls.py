from django.urls import path
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
app_name = 'acctmgt'

urlpatterns = [
    # Login/Logout
    path('login/', auth_views.LoginView.as_view(
        template_name='acctmgt/login.html',
        redirect_authenticated_user=True
    ), name='login'),
    
    path('logout/', auth_views.LogoutView.as_view(
        next_page=reverse_lazy('acctmgt:login')     
    ), name='logout'),
]
