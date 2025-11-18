# Network Access Guide - Making Your App Accessible from Different Networks

## Option 1: ngrok (Easiest for Testing) - RECOMMENDED

ngrok creates a secure tunnel to your local server, giving you a public URL.

### Steps:

1. **Download ngrok**:
   - Go to https://ngrok.com/download
   - Download for Windows
   - Extract the `ngrok.exe` file

2. **Run your FastAPI app**:
   ```bash
   uvicorn app:app --host 0.0.0.0 --port 8000 --reload
   ```

3. **In a new terminal, run ngrok**:
   ```bash
   ngrok http 8000
   ```

4. **Get your public URL**:
   - ngrok will display a URL like: `https://abc123.ngrok-free.app`
   - Share this URL with anyone, anywhere
   - They can access your app at: `https://abc123.ngrok-free.app`

### ngrok Features:
- ✅ Free tier available
- ✅ HTTPS automatically
- ✅ Works immediately
- ✅ No router configuration needed
- ⚠️ Free tier: URLs change each time you restart ngrok
- ⚠️ Free tier: May have connection limits

### For a permanent URL (paid ngrok):
```bash
ngrok http 8000 --domain=your-custom-name.ngrok-free.app
```

---

## Option 2: Port Forwarding (For Permanent Access)

This makes your app accessible via your public IP address.

### Steps:

1. **Find your public IP**:
   - Visit: https://whatismyipaddress.com/
   - Or run: `curl ifconfig.me` (if you have curl)

2. **Configure your router**:
   - Log into your router admin panel (usually `192.168.1.1` or `192.168.0.1`)
   - Find "Port Forwarding" or "Virtual Server" settings
   - Forward external port 8000 to internal IP `10.10.21.38:8000`
   - Protocol: TCP

3. **Security Considerations**:
   - ⚠️ Your app will be exposed to the internet
   - ✅ You have authentication (login) which helps
   - ⚠️ Consider using a non-standard port (not 8000)
   - ⚠️ Make sure your firewall allows the port

4. **Access from anywhere**:
   - `http://YOUR_PUBLIC_IP:8000`
   - Example: `http://203.0.113.50:8000`

### Important Notes:
- Your public IP may change (unless you have a static IP)
- You may need to configure Windows Firewall
- Your ISP may block incoming connections on port 8000

---

## Option 3: Cloud Deployment (Best for Production)

Deploy to a cloud service for permanent, reliable access.

### Option 3a: Railway (Free Tier Available)

1. **Install Railway CLI**:
   ```bash
   npm install -g @railway/cli
   ```

2. **Login and deploy**:
   ```bash
   railway login
   railway init
   railway up
   ```

3. **Get your URL**:
   - Railway provides a public URL automatically
   - Example: `https://your-app.railway.app`

### Option 3b: Render (Free Tier Available)

1. **Create account** at https://render.com
2. **Create new Web Service**
3. **Connect your GitHub repository** (or upload files)
4. **Build command**: `pip install -r requirements.txt`
5. **Start command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
6. **Set environment variable**: `SECRET_KEY=your-secret-key`

### Option 3c: PythonAnywhere (Free Tier Available)

1. **Create account** at https://www.pythonanywhere.com
2. **Upload your files** via web interface
3. **Configure web app** to run your FastAPI app
4. **Get your URL**: `https://yourusername.pythonanywhere.com`

---

## Option 4: VPN (For Secure Access)

If you want secure access without exposing to the internet:

1. **Set up a VPN server** (WireGuard, OpenVPN, etc.)
2. **Users connect via VPN**
3. **Access via local IP**: `http://10.10.21.38:8000`

This is more complex but very secure.

---

## Quick Comparison

| Method | Ease | Cost | Security | Permanent URL |
|--------|------|------|----------|---------------|
| ngrok | ⭐⭐⭐⭐⭐ | Free/Paid | Good | No (free) / Yes (paid) |
| Port Forwarding | ⭐⭐⭐ | Free | Moderate | Yes (if static IP) |
| Cloud (Railway/Render) | ⭐⭐⭐⭐ | Free/Paid | Good | Yes |
| VPN | ⭐⭐ | Free/Paid | Excellent | N/A |

---

## Recommended Approach

**For quick testing**: Use **ngrok** (Option 1)
- Fastest setup
- Works immediately
- Good for demos/testing

**For production**: Use **Cloud Deployment** (Option 3)
- Reliable
- Professional
- Better performance
- Free tiers available

---

## Security Reminders

⚠️ **IMPORTANT**: Before exposing your app to the internet:

1. ✅ Change default credentials in `whitelist.json`
2. ✅ Set a strong `SECRET_KEY` environment variable
3. ✅ Consider rate limiting
4. ✅ Use HTTPS (ngrok and cloud services provide this automatically)
5. ✅ Keep your dependencies updated
6. ✅ Monitor access logs

---

## Troubleshooting

### Can't access from outside network:
- Check Windows Firewall settings
- Verify router port forwarding (if using Option 2)
- Check if your ISP blocks incoming connections
- Try a different port (8001, 8080, etc.)

### ngrok not working:
- Make sure your local server is running first
- Check if port 8000 is correct
- Try: `ngrok http 8000 --region us` (specify region)

### Cloud deployment issues:
- Check build logs in the service dashboard
- Verify all dependencies in `requirements.txt`
- Check environment variables are set correctly

