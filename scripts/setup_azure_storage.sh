#!/bin/bash
# =============================================================================
# SOLVEREIGN - Azure Storage Setup Script
# =============================================================================
# Creates storage account with lifecycle policy for evidence artifacts.
#
# Usage:
#   ./scripts/setup_azure_storage.sh <resource-group> <storage-account-name> <location>
#
# Example:
#   ./scripts/setup_azure_storage.sh rg-solvereign-prod stsolvereign westeurope
# =============================================================================

set -euo pipefail

RESOURCE_GROUP="${1:-}"
STORAGE_ACCOUNT="${2:-}"
LOCATION="${3:-westeurope}"
CONTAINER_NAME="solvereign-artifacts"

if [[ -z "$RESOURCE_GROUP" || -z "$STORAGE_ACCOUNT" ]]; then
    echo "Usage: $0 <resource-group> <storage-account-name> [location]"
    exit 1
fi

echo "=== SOLVEREIGN Azure Storage Setup ==="
echo "Resource Group: $RESOURCE_GROUP"
echo "Storage Account: $STORAGE_ACCOUNT"
echo "Location: $LOCATION"
echo "Container: $CONTAINER_NAME"
echo ""

# 1. Create Storage Account (Standard LRS as per user decision)
echo "[1/5] Creating storage account..."
az storage account create \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku Standard_LRS \
    --kind StorageV2 \
    --access-tier Hot \
    --min-tls-version TLS1_2 \
    --allow-blob-public-access false \
    --https-only true

# 2. Create container
echo "[2/5] Creating blob container..."
az storage container create \
    --name "$CONTAINER_NAME" \
    --account-name "$STORAGE_ACCOUNT" \
    --auth-mode login

# 3. Apply lifecycle policy
echo "[3/5] Applying lifecycle policy..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLICY_FILE="$SCRIPT_DIR/../backend_py/config/azure_lifecycle_policy.json"

az storage account management-policy create \
    --account-name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --policy "@$POLICY_FILE"

# 4. Enable soft delete (30 days)
echo "[4/5] Enabling soft delete..."
az storage blob service-properties delete-policy update \
    --account-name "$STORAGE_ACCOUNT" \
    --enable true \
    --days-retained 30

# 5. Output configuration
echo "[5/5] Configuration complete!"
echo ""
echo "=== Configuration for .env ==="
echo ""
echo "# Option A: Connection String (Pilot mode)"
CONNECTION_STRING=$(az storage account show-connection-string \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --query connectionString -o tsv)
echo "AZURE_STORAGE_CONNECTION_STRING=\"$CONNECTION_STRING\""
echo ""
echo "# Option B: Managed Identity (Production mode)"
ACCOUNT_URL="https://${STORAGE_ACCOUNT}.blob.core.windows.net"
echo "AZURE_STORAGE_ACCOUNT_URL=\"$ACCOUNT_URL\""
echo "AZURE_STORAGE_CONTAINER=\"$CONTAINER_NAME\""
echo ""
echo "=== Next Steps ==="
echo "1. For Managed Identity: Assign 'Storage Blob Data Contributor' role to your App Service/AKS identity"
echo "   az role assignment create --assignee <identity-principal-id> --role 'Storage Blob Data Contributor' --scope /subscriptions/<sub>/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT"
echo ""
echo "2. Test with: az storage blob list --container-name $CONTAINER_NAME --account-name $STORAGE_ACCOUNT --auth-mode login"
