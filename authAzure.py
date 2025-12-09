import os
from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer

# Azure AD Configuration
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "ab608ebc-7163-416a-ba6d-fb2f885d8914")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "2ac3d243-3f81-4a69-b696-de7aca29bbfb")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
AZURE_REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI", "http://localhost:8000/auth/callback")

# Mailbox access restriction
# Set this to the email address of the mailbox users must have access to
# Leave empty to disable mailbox access checking
REQUIRED_MAILBOX = os.getenv("REQUIRED_MAILBOX", "")

# Azure scheme for API authentication (Bearer tokens)
azure_scheme = SingleTenantAzureAuthorizationCodeBearer(
    app_client_id=AZURE_CLIENT_ID,
    tenant_id=AZURE_TENANT_ID,
    scopes={'api://ab608ebc-7163-416a-ba6d-fb2f885d8914/userImpersonations': 'access as user'},
    allow_guest_users=True,
)

# Azure OAuth2 endpoints
AZURE_AUTHORIZATION_ENDPOINT = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/authorize"
AZURE_TOKEN_ENDPOINT = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/token"

# Microsoft Graph API endpoint
GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"