import os

BASE = os.path.dirname(os.path.abspath(__file__))
NGINX_DIR = os.path.join(BASE, 'nginx')

os.makedirs(NGINX_DIR, exist_ok=True)
print(f'✓ Created: {NGINX_DIR}')

NGINX_CONF = r'''upstream api_server {
    server api:8000;
}

upstream frontend_server {
    server frontend:3000;
}

server {
    listen 80;
    server_name localhost;

    # API proxy
    location /api/ {
        proxy_pass http://api_server;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket proxy
    location /ws/ {
        proxy_pass http://api_server;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }

    # Frontend proxy (production: serve static files from container)
    location / {
        proxy_pass http://frontend_server;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
'''

conf_path = os.path.join(NGINX_DIR, 'default.conf')
with open(conf_path, 'w', newline='\n') as f:
    f.write(NGINX_CONF.lstrip('\n'))
print(f'✓ Written: {conf_path}')

print('\nDone. nginx/default.conf is ready.')
