import os

# Create the required directories
dirs = [
    r'E:\pdf\capston01\walletSavior\admin\admin-api',
    r'E:\pdf\capston01\walletSavior\admin\admin-frontend'
]

for dir_path in dirs:
    os.makedirs(dir_path, exist_ok=True)
    print(f'Created: {dir_path}')

# Verify they exist
print('\nVerifying directories:')
for dir_path in dirs:
    if os.path.isdir(dir_path):
        print(f'✓ {dir_path} exists')
    else:
        print(f'✗ {dir_path} does NOT exist')
