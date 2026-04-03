#!/usr/bin/env python3
import os
from pathlib import Path

# Create both directories
paths = [
    r'E:\pdf\capston01\walletSavior\.github\workflows',
    r'E:\pdf\capston01\walletSavior\.github\ISSUE_TEMPLATE'
]

print("Creating directories...\n")
for p in paths:
    Path(p).mkdir(parents=True, exist_ok=True)
    print(f"✓ Created: {p}")

print("\n" + "="*60)
print("VERIFICATION - Directory Contents")
print("="*60)

# Verify
github_path = Path(r'E:\pdf\capston01\walletSavior\.github')

print("\n=== .github directory contents ===")
try:
    items = sorted(github_path.iterdir())
    for item in items:
        print(f"  {'[DIR]':6} {item.name}")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== workflows directory contents ===")
try:
    workflows = list(Path(paths[0]).iterdir())
    if workflows:
        for item in sorted(workflows):
            print(f"  {'[FILE]':6} {item.name}")
    else:
        print("  (empty directory)")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== ISSUE_TEMPLATE directory contents ===")
try:
    templates = list(Path(paths[1]).iterdir())
    if templates:
        for item in sorted(templates):
            print(f"  {'[FILE]':6} {item.name}")
    else:
        print("  (empty directory)")
except Exception as e:
    print(f"  Error: {e}")

print("\n" + "="*60)
print("✓ All directories created and verified successfully!")
print("="*60)
