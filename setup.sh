#!/bin/bash

# turboship-setup.sh
# Turboship EC2 Bootstrap Script - Sets up environment for hosting Node+React+DB projects

set -e

LOGFILE="/var/log/turboship-setup.log"
exec > >(tee -a $LOGFILE) 2>&1

# Variables
WWW_DIR="/var/www"
SSH_CONFIG="/etc/ssh/sshd_config"

# 1. Update & Install Dependencies
echo "📦 Updating system and installing dependencies..."
sudo apt update && sudo apt upgrade -y || { echo "System update failed"; exit 1; }
sudo apt install -y nginx python3 python3-pip python3-venv git mariadb-server postgresql postgresql-contrib acl ufw unzip openssh-server || { echo "Dependency installation failed"; exit 1; }

# 2. Python Packages for CLI
echo "🐍 Installing Python packages..."
sudo pip3 install --break-system-packages tabulate colorama || { echo "Python package installation failed"; exit 1; }

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
mkdir -p $WWW_DIR
sudo chmod 755 $WWW_DIR

# 6. Enable MariaDB & PostgreSQL
echo "🔐 Enabling database services..."
sudo systemctl enable mariadb
sudo systemctl start mariadb
sudo systemctl enable postgresql
sudo systemctl start postgresql

# 7. Configure MariaDB for remote access
echo "🌐 Configuring MariaDB for remote access..."
sudo sed -i "s/^bind-address\s*=\s*127.0.0.1/bind-address = 0.0.0.0/" /etc/mysql/mariadb.conf.d/50-server.cnf || { echo "MariaDB configuration failed"; exit 1; }
sudo systemctl restart mariadb

# 8. Configure PostgreSQL for remote access
echo "🌐 Configuring PostgreSQL for remote access..."
echo "host    all             all             0.0.0.0/0               md5" | sudo tee -a /etc/postgresql/*/main/pg_hba.conf
sudo sed -i "s|^#listen_addresses = 'localhost'|listen_addresses = '*'|" /etc/postgresql/*/main/postgresql.conf || { echo "PostgreSQL configuration failed"; exit 1; }
sudo systemctl restart postgresql

# 9. Configure SSH for SFTP with chroot
echo "🔧 Configuring SSH for SFTP"

# SSH config: Enable password & interactive auth
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' $SSH_CONFIG
sudo sed -i 's/^#\?KbdInteractiveAuthentication.*/KbdInteractiveAuthentication yes/' $SSH_CONFIG
sudo sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' $SSH_CONFIG
sudo sed -i 's/^#\?UsePAM.*/UsePAM yes/' $SSH_CONFIG

# Configure chroot for SFTP users
# if ! grep -q "Match Group sftpusers" $SSH_CONFIG; then
#   sudo bash -c 'cat <<EOT >> $SSH_CONFIG
# Match Group sftpusers
#     ChrootDirectory /var/www/%u
#     ForceCommand internal-sftp
#     AllowTcpForwarding no
#     X11Forwarding no
# EOT'
# fi

# Ensure proper permissions for chroot directories
sudo chown root:root $WWW_DIR
sudo chmod 755 $WWW_DIR

# Restart SSH to apply changes
sudo systemctl restart ssh || { echo "SSH configuration failed"; exit 1; }

echo "✅ SSH configuration updated with chroot for SFTP users."

# 10. Done
echo "✅ Turboship environment setup is complete. Ready to launch projects!"
echo "👉 Run python3 turboship.py to create a project."
