# Running the App Locally with ngrok

This guide will help you run your Batch Invoicer app locally and expose it to the internet using ngrok.

## Step 1: Install ngrok

### Windows:
1. Go to https://ngrok.com/download
2. Download the Windows version
3. Extract `ngrok.exe` to a folder (e.g., `C:\ngrok\`)
4. Add ngrok to your PATH (optional but recommended):
   - Right-click "This PC" → Properties → Advanced system settings
   - Click "Environment Variables"
   - Under "System variables", find "Path" and click "Edit"
   - Click "New" and add the path where you extracted ngrok (e.g., `C:\ngrok`)
   - Click OK on all dialogs

### Alternative: Use Chocolatey (if installed)
```powershell
choco install ngrok
```

## Step 2: Start Your FastAPI Application

Open a terminal/PowerShell in your project directory and run:

```bash
# Make sure you're in the project directory
cd "C:\Users\VictorMendoza\Desktop\Batch Invoicer"

# Activate your virtual environment (if you have one)
# venv\Scripts\activate

# Install dependencies (if not already installed)
pip install -r requirements.txt

# Start the FastAPI app
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

You should see output like:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**Keep this terminal window open!**

## Step 3: Start ngrok

Open a **new** terminal/PowerShell window and run:

```bash
ngrok http 8000
```

You should see output like:
```
ngrok

Session Status                online
Account                       Your Account (Plan: Free)
Version                       3.x.x
Region                        United States (us)
Latency                       -
Web Interface                 http://127.0.0.1:4040
Forwarding                    https://abc123.ngrok-free.app -> http://localhost:8000

Connections                   ttl     opn     rt1     rt5     p50     p90
                              0       0       0.00    0.00    0.00    0.00
```

## Step 4: Access Your App

1. **Copy the forwarding URL** from ngrok (e.g., `https://abc123.ngrok-free.app`)
2. **Open it in your browser**
3. You should see your login page!

## Important Notes

### ngrok Free Tier Limitations:
- ⚠️ **URL changes each time** you restart ngrok (unless you have a paid plan)
- ⚠️ **Connection limits** may apply on free tier
- ⚠️ **Warning page** may appear on first visit (click "Visit Site" to continue)

### Security:
- ✅ Your app has authentication (login required)
- ✅ HTTPS is automatically provided by ngrok
- ⚠️ The URL is public - anyone with the link can try to access it
- ⚠️ Make sure your `SECRET_KEY` is set and `whitelist.json` has secure credentials

### Stopping:
- Press `CTRL+C` in both terminal windows to stop
- Stop ngrok first, then stop the FastAPI app

## Troubleshooting

### ngrok command not found:
- Make sure ngrok is installed and in your PATH
- Or use the full path: `C:\ngrok\ngrok.exe http 8000`

### Port 8000 already in use:
- Check what's using port 8000:
  ```powershell
  netstat -ano | findstr :8000
  ```
- Kill the process or use a different port:
  ```bash
  uvicorn app:app --host 127.0.0.1 --port 8001 --reload
  ngrok http 8001
  ```

### Can't access the ngrok URL:
- Make sure both the FastAPI app and ngrok are running
- Check the ngrok web interface: http://127.0.0.1:4040
- Look at the ngrok terminal for error messages

### App shows error when accessed via ngrok:
- Check the FastAPI terminal for error messages
- Make sure the app is running on `127.0.0.1:8000` (not `0.0.0.0`)
- Verify your `whitelist.json` exists and has valid users

## Quick Commands Reference

```bash
# Terminal 1: Start FastAPI
uvicorn app:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2: Start ngrok
ngrok http 8000

# View ngrok web interface (optional)
# Open browser to: http://127.0.0.1:4040
```

## Testing with ngrok

Once running, you can:
1. Share the ngrok URL with others to test
2. Test on mobile devices using the ngrok URL
3. Use it for webhook testing (if you add webhooks later)
4. Test from different networks

## Next Steps

After testing locally with ngrok, you can:
- Deploy to Azure App Service (see `AZURE_DEPLOYMENT.md`)
- Set up a permanent domain with ngrok (paid plan)
- Configure custom domain on Azure

