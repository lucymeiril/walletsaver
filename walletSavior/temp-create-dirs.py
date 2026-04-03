#!/usr/bin/env python3
import os
from pathlib import Path
import sys

try:
    dirs = [
        r'E:\pdf\capston01\walletSavior\.github\workflows',
        r'E:\pdf\capston01\walletSavior\.github\ISSUE_TEMPLATE'
    ]
    
    for directory in dirs:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f'Created: {directory}')
    
    print('\n✓ All directories created successfully!')
    sys.exit(0)
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
