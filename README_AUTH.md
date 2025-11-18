# Authentication Setup

## Default Credentials
- **Username**: `admin`
- **Password**: `admin123`

**⚠️ IMPORTANT**: Change these default credentials immediately in production!

## Adding Users to Whitelist

### Method 1: Edit `whitelist.json` directly

Edit the `whitelist.json` file and add users:

```json
{
    "users": [
        {
            "username": "admin",
            "password": "admin123"
        },
        {
            "username": "user1",
            "password": "password123"
        }
    ]
}
```

### Method 2: Use Python script (with password hashing)

You can use the `auth.py` module to add users with hashed passwords:

```python
from auth import add_user_to_whitelist, hash_password

# Add user with hashed password
add_user_to_whitelist("newuser", "securepassword", hash_password_flag=True)
```

## Security Notes

1. **Change Default Password**: The default admin password should be changed immediately.

2. **Password Hashing**: For better security, use hashed passwords:
   - Set `"password_hash"` instead of `"password"` in the whitelist
   - Use the `hash_password()` function from `auth.py` to generate hashes

3. **Secret Key**: Change the `SECRET_KEY` in `auth.py` or set it as an environment variable:
   ```bash
   export SECRET_KEY="your-very-secure-secret-key-here"
   ```

4. **HTTPS in Production**: Set `secure=True` in the cookie settings in `app.py` when using HTTPS.

5. **Session Duration**: Default session is 24 hours. Adjust `max_age` in the login endpoint if needed.

## Environment Variables

For production, set these environment variables:

```bash
export SECRET_KEY="your-secret-key-here"
```

This will override the default secret key in `auth.py`.

