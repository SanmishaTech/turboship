#!/bin/bash

echo "🚀 Starting Turboship Server Setup..."
echo "====================================="

# Exit on error
set -e

# Update & install core packages
echo "📦 Updating packages and installing system dependencies..."
sudo apt update
sudo apt install -y nginx mariadb-server postgresql sqlite3 python3 python3-pip ufw

# Install Python dependencies required by turboship
echo "🐍 Installing Python packages..."
python3 -m pip install --upgrade pip --break-system-packages
python3 -m pip install --break-system-packages tabulate rich

# Verify Python packages
if ! python3 -c "import tabulate, rich"; then
  echo "❌ Failed to install Python dependencies."
  exit 1
fi

# Enable and start services
echo "🛠 Enabling and starting services..."
sudo systemctl enable --now nginx
sudo systemctl enable --now mariadb
sudo systemctl enable --now postgresql

# Basic firewall setup
echo "🧱 Configuring UFW firewall..."
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable

# Create turboship directory
echo "📁 Setting up project directory structure..."
sudo mkdir -p /opt/turboship/projects
sudo mkdir -p /opt/turboship/logs
sudo mkdir -p /opt/turboship/db
sudo chown -R "$USER":"$USER" /opt/turboship

# Clone repo if not already present
if [ ! -d "/home/$USER/turboship" ]; then
  echo "📥 Cloning Turboship from GitHub..."
  git clone https://github.com/SanmishaTech/turboship.git /home/$USER/turboship
fi

# Reminder
echo -e "\n✅ Turboship setup completed!"
echo "👉 To run the main script:"
echo "   python3 /home/$USER/turboship/scripts/turboship.py"
