from django.db import models
from django.contrib.auth.models import User
import json

class FileProcessingTask(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('awaiting_verification', 'Awaiting Verification'),
        ('finalizing', 'Finalizing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    task_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    filename = models.CharField(max_length=255)
    subscriber_alias = models.CharField(max_length=100)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='pending')
    progress = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    error_message = models.TextField(blank=True, null=True)
    result_file_path = models.CharField(max_length=500, blank=True, null=True)
    intermediate_data = models.JSONField(blank=True, null=True)
    results_data = models.JSONField(blank=True, null=True)  # Store final processing results
    
    def __str__(self):
        return f"{self.filename} - {self.status}"