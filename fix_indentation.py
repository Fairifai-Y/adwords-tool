#!/usr/bin/env python3

# Fix indentation issues in create_seller_bucket_campaigns.py

with open('src/create_seller_bucket_campaigns.py', 'r') as f:
    lines = f.readlines()

# Fix line 198 - add proper indentation
lines[197] = '                    campaign_name = f"{seller} - {config_type} - {bucket}"\n'

# Fix the rest of the indentation in the for loop
for i in range(198, min(220, len(lines))):
    if lines[i].strip() and not lines[i].startswith('        '):
        # Add proper indentation (4 more spaces)
        lines[i] = '                    ' + lines[i].lstrip()

with open('src/create_seller_bucket_campaigns.py', 'w') as f:
    f.writelines(lines)

print("Indentation fixed!")
