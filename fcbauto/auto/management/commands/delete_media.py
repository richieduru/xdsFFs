import os
import shutil
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = 'Deletes the media folder and all its contents.'

    def handle(self, *args, **options):
        media_path = settings.MEDIA_ROOT
        if os.path.exists(media_path):
            shutil.rmtree(media_path)
            self.stdout.write(self.style.SUCCESS(f'Successfully deleted {media_path}'))
            os.makedirs(media_path)  # Recreate the folder if needed
        else:
            self.stdout.write(self.style.WARNING(f'{media_path} does not exist.')) 