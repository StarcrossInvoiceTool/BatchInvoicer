# Azure App Service Deployment Guide

This guide will help you deploy the Batch Invoicer application to Azure App Service.

## Prerequisites

1. **Azure Account**: Sign up at https://azure.microsoft.com/free/
2. **Azure CLI**: Install from https://docs.microsoft.com/en-us/cli/azure/install-azure-cli
3. **Git**: Your code should be in a Git repository (GitHub, Azure DevOps, etc.)

## Step 1: Prepare Your Application

Your application is already configured with:
- ✅ `requirements.txt` - Python dependencies
- ✅ `startup.sh` - Startup script for Azure
- ✅ Application code ready for deployment

## Step 2: Create Azure App Service

### Option A: Using Azure Portal (Recommended for beginners)

1. **Log in to Azure Portal**: https://portal.azure.com

2. **Create a new App Service**:
   - Click "Create a resource"
   - Search for "Web App"
   - Click "Create"

3. **Configure the App Service**:
   - **Subscription**: Choose your subscription
   - **Resource Group**: Create new or use existing
   - **Name**: `batchinvoicer` (or your preferred name)
   - **Publish**: Code
   - **Runtime stack**: Python 3.11 (or 3.9+)
   - **Operating System**: Linux (recommended) or Windows
   - **Region**: Choose closest to your users
   - **App Service Plan**: 
     - Create new plan
     - **Sku and size**: Free F1 (for testing) or Basic B1 (for production)
   
4. **Click "Review + create"** then **"Create"**

5. **Wait for deployment** (2-3 minutes)

### Option B: Using Azure CLI

```bash
# Login to Azure
az login

# Create a resource group
az group create --name batchinvoicer-rg --location eastus

# Create App Service plan (Free tier)
az appservice plan create --name batchinvoicer-plan --resource-group batchinvoicer-rg --sku FREE --is-linux

# Create the web app
az webapp create --resource-group batchinvoicer-rg --plan batchinvoicer-plan --name batchinvoicer --runtime "PYTHON|3.11" --deployment-local-git
```

## Step 3: Configure Application Settings

### In Azure Portal:

1. Go to your App Service
2. Navigate to **Configuration** → **Application settings**
3. Add the following environment variables:

   | Name | Value | Description |
   |------|-------|-------------|
   | `SECRET_KEY` | `your-very-secure-secret-key-here` | Secret key for session signing (generate a strong random string) |
   | `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` | Enable build during deployment |
   | `ENABLE_ORYX_BUILD` | `true` | Enable Oryx build system |

4. **Save** the settings

### Using Azure CLI:

```bash
az webapp config appsettings set --resource-group batchinvoicer-rg --name batchinvoicer --settings SECRET_KEY="your-very-secure-secret-key-here" SCM_DO_BUILD_DURING_DEPLOYMENT=true ENABLE_ORYX_BUILD=true
```

## Step 4: Configure Startup Command

### In Azure Portal:

1. Go to **Configuration** → **General settings**
2. Set **Startup Command** to:
   ```
   startup.sh
   ```
   Or directly:
   ```
   uvicorn app:app --host 0.0.0.0 --port $PORT --workers 2
   ```

### Using Azure CLI:

```bash
az webapp config set --resource-group batchinvoicer-rg --name batchinvoicer --startup-file "startup.sh"
```

## Step 5: Deploy Your Code

### Option A: Deploy from GitHub (Recommended)

1. **In Azure Portal**:
   - Go to your App Service
   - Navigate to **Deployment Center**
   - Select **GitHub** as source
   - Authorize Azure to access your GitHub
   - Select your repository: `VictorMG11/BatchInvoicer`
   - Select branch: `main` (or `master`)
   - Click **Save**

2. **Azure will automatically deploy** when you push to the selected branch

### Option B: Deploy using Azure CLI with Local Git

```bash
# Add Azure as a remote
az webapp deployment source config-local-git --name batchinvoicer --resource-group batchinvoicer-rg

# Get the deployment URL (shown in output)
# It will look like: https://<username>@batchinvoicer.scm.azurewebsites.net/batchinvoicer.git

# Add Azure remote to your local repository
git remote add azure https://<username>@batchinvoicer.scm.azurewebsites.net/batchinvoicer.git

# Deploy
git push azure main
```

### Option C: Deploy using ZIP

```bash
# Create a ZIP file of your project (excluding venv, temp, etc.)
# Then use Azure CLI:
az webapp deployment source config-zip --resource-group batchinvoicer-rg --name batchinvoicer --src deploy.zip
```

## Step 6: Set Up Whitelist (User Authentication)

Since `whitelist.json` is in `.gitignore`, you need to create it on Azure:

### Option A: Using Azure Portal

1. Go to **Development Tools** → **SSH** (or **Console**)
2. Navigate to `/home/site/wwwroot`
3. Create `whitelist.json`:
   ```bash
   cat > whitelist.json << 'EOF'
   {
       "users": [
           {
               "username": "admin",
               "password_hash": "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyY5Y5Y5Y5Y5"
           }
       ]
   }
   EOF
   ```
   (Replace with your actual password hash - use `auth.py` to generate)

### Option B: Using Azure CLI

```bash
# Create whitelist.json locally with your users
# Then upload it:
az webapp deployment source config-zip --resource-group batchinvoicer-rg --name batchinvoicer --src whitelist.zip
```

### Option C: Use Application Settings (Recommended)

Modify `auth.py` to also check environment variables for users, or use Azure Key Vault.

## Step 7: Verify Deployment

1. **Check deployment logs**:
   - Go to **Deployment Center** → **Logs**
   - Verify build succeeded

2. **Check application logs**:
   - Go to **Log stream** or **Logs** → **Application Logging**
   - Look for startup messages

3. **Test your application**:
   - Visit: `https://batchinvoicer.azurewebsites.net`
   - You should see the login page

## Step 8: Configure Custom Domain (Optional)

1. Go to **Custom domains** in your App Service
2. Add your domain
3. Follow the DNS configuration instructions

## Troubleshooting

### Application won't start

- **Check startup command**: Must be `startup.sh` or the full uvicorn command
- **Check logs**: Go to **Log stream** to see error messages
- **Verify Python version**: Should match your `requirements.txt` (Python 3.11)

### 500 Internal Server Error

- **Check application logs**: Look for Python errors
- **Verify environment variables**: Ensure `SECRET_KEY` is set
- **Check file permissions**: Ensure `startup.sh` is executable

### Can't access the application

- **Check App Service is running**: Status should be "Running"
- **Check firewall rules**: App Service should allow all traffic by default
- **Try restarting**: Go to **Overview** → **Restart**

### Build fails

- **Check requirements.txt**: All dependencies must be valid
- **Check Python version**: Azure must support the version you're using
- **Check build logs**: Look for specific error messages

## Security Checklist

Before going to production:

- [ ] Change default `SECRET_KEY` to a strong random value
- [ ] Update default admin credentials in `whitelist.json`
- [ ] Enable HTTPS only (in **TLS/SSL settings**)
- [ ] Configure authentication if needed (Azure AD, etc.)
- [ ] Set up monitoring and alerts
- [ ] Configure backup strategy
- [ ] Review and update dependencies regularly

## Cost Optimization

- **Free Tier (F1)**: 
  - 1 GB storage
  - 60 minutes CPU/day
  - Good for testing/development
  
- **Basic Tier (B1)**:
  - Better performance
  - No time limits
  - ~$13/month (prices vary by region)

## Next Steps

1. Set up **Application Insights** for monitoring
2. Configure **Auto-scaling** if needed
3. Set up **Staging slots** for testing deployments
4. Configure **Backup** strategy
5. Set up **CI/CD pipeline** for automated deployments

## Useful Commands

```bash
# View logs
az webapp log tail --name batchinvoicer --resource-group batchinvoicer-rg

# Restart app
az webapp restart --name batchinvoicer --resource-group batchinvoicer-rg

# View app settings
az webapp config appsettings list --name batchinvoicer --resource-group batchinvoicer-rg

# Update app settings
az webapp config appsettings set --name batchinvoicer --resource-group batchinvoicer-rg --settings KEY="value"
```

## Support

- Azure Documentation: https://docs.microsoft.com/azure/app-service/
- FastAPI Documentation: https://fastapi.tiangolo.com/
- Azure Status: https://status.azure.com/

