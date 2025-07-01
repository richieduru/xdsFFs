# First Credit Bureau - Admin Guide

## User Management

### Creating New Users
1. Log in to the admin interface at `/admin/` using your superuser credentials
2. Click on "Users" in the admin dashboard
3. Click "ADD USER +" in the top right
4. Enter the username and password for the new user
5. Check "Staff status" to give admin access
6. Click "Save" to create the user

### User Types
- **Regular Users**: Can log in and use the application
- **Staff Users (is_staff)**: Can access the admin interface
- **Superusers**: Full admin access (can create/delete users)

### Creating a Superuser (First Time Setup)
Run this command in your terminal:
```bash
python manage.py createsuperuser
```

### Resetting Passwords
1. Go to `/admin/auth/user/`
2. Click on the username
3. Click "This form" link under password field
4. Enter new password and confirm
5. Click "Change my password"

## Security Best Practices
- Never share admin credentials
- Use strong, unique passwords
- Regularly audit user accounts
- Remove inactive users
- Keep the Django secret key secure

## Troubleshooting
- If you can't log in, contact a superuser to reset your password
- For admin access issues, verify the user has "Staff status" enabled
