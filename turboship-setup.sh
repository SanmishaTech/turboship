#!/bin/bash

echo "🔧 Updating system..."
sudo apt update && sudo apt upgrade -y

echo "🧰 Installing essential tools..."
sudo apt install curl git ufw unzip -y

echo "🌐 Installing NGINX..."
sudo apt install nginx -y
sudo systemctl enable nginx
sudo systemctl start nginx

echo "🟨 Installing Node.js 18 & PM2..."
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs build-essential
sudo npm install -g pm2
pm2 startup systemd -u ubuntu --hp /home/ubuntu

echo "🗄️ Installing MySQL..."
sudo apt install mysql-server -y
sudo systemctl enable mysql
sudo systemctl start mysql
sudo mysql_secure_installation

echo "🔐 Installing Certbot for SSL..."
sudo apt install certbot python3-certbot-nginx -y

echo "🔥 Configuring Firewall (UFW)..."
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable

echo "✅ Turboship base setup complete!"
