#!/bin/bash

# turboship-setup.sh
# Turboship EC2 Bootstrap Script - Sets up environment for hosting Node+React+DB projects

set -e

# 1. Update & Install Dependencies
echo "📦 Updating system and installing dependencies..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y nginx python3 python3-pip python3-venv git mariadb-server postgresql postgresql-contrib acl ufw unzip

# 2. Python Packages for CLI
echo "🐍 Installing Python packages..."
sudo pip3 install tabulate colorama

# 3. Setup NGINX
sudo systemctl enable nginx
sudo systemctl start nginx

# 4. Setup UFW
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw allow 3306/tcp  # MySQL Remote Access
sudo ufw allow 5432/tcp  # PostgreSQL Remote Access
sudo ufw --force enable

# 5. Setup Directories
mkdir -p /var/www
sudo chmod 755 /var/www

# 6. Enable MariaDB & PostgreSQL
echo "🔐 Enabling database services..."
sudo systemctl enable mariadb
sudo systemctl start mariadb
sudo systemctl enable postgresql
sudo systemctl start postgresql

# 7. Configure MariaDB for remote access
echo "🌐 Configuring MariaDB for remote access..."
sudo sed -i "s/^bind-address\s*=\s*127.0.0.1/bind-address = 0.0.0.0/" /etc/mysql/mariadb.conf.d/50-server.cnf
sudo systemctl restart mariadb

# 8. Configure PostgreSQL for remote access
echo "🌐 Configuring PostgreSQL for remote access..."
echo "host    all             all             0.0.0.0/0               md5" | sudo tee -a /etc/postgresql/*/main/pg_hba.conf
sudo sed -i "s/^#listen_addresses = 'localhost'/listen_addresses = '*'/'" /etc/postgresql/*/main/postgresql.conf
sudo systemctl restart postgresql

# 9. Done
echo "✅ Turboship environment setup is complete. Ready to launch projects!"
echo "👉 Run python3 turboship.py to create a project."
