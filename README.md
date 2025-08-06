# 🚀 Turboship

Turboship is a simple, flexible deployment tool to manage multiple Node.js + React + SQL (MariaDB/PostgreSQL) based applications on a single Linux server (e.g., AWS EC2).  
No Docker. No bloated panels. Just efficient CLI + scripts.

---

## 📦 Project Features

- [x] Host multiple full-stack apps (React frontend + Node.js backend)
- [x] Create project directories, databases, and users with one command
- [x] Install MariaDB & PostgreSQL — choose what works for your app
- [x] PM2 for backend process management
- [x] NGINX as reverse proxy + Let's Encrypt SSL
- [x] UFW firewall preconfigured
- [ ] Option to restore from backup
- [ ] Email notifications on new setup/removal
- [x] Add real domain mapping support
- [x] Enable reverse domain lookup
- [x] Add interactive help (--help)
- [x] Customize the landing page style/content.
- [ ] Include database backup also
- [ ] Suspend an app temporarily

---

## 📁 Project Structure

```
/opt/turboship/turboship.db  # SQLite database for app metadata
/var/www/<app_name>_sftp    # App root directory
/var/www/<app_name>_sftp/htdocs  # Frontend files
/var/www/<app_name>_sftp/api     # Backend files
/var/www/<app_name>_sftp/logs    # Logs directory
```

---

## 🛠️ Installation

1. Download the setup script using `curl`:
   ```bash
   curl -O https://raw.githubusercontent.com/SanmishaTech/turboship/main/setup.sh
   ```

2. Run the setup script:
   ```bash
   sudo bash setup.sh
   ```

---

## 🚀 Usage

### Create a New App
```bash
python3 turboship.py create --domain example.com
```

### Test an App
```bash
python3 turboship.py test <app_name>
```

### List All Apps
```bash
python3 turboship.py list
```

### Delete an App
```bash
python3 turboship.py delete <app_name>
```

### Map a Real Domain
```bash
python3 turboship.py map-domain <app_name> --domain example.com
```

### Display App Info
```bash
python3 turboship.py info <app_name>
```

### Interactive Mode
Run the CLI interactively:
```bash
python3 turboship.py
```

---

## 🔧 Configuration

### NGINX
NGINX configuration files are stored in `/etc/nginx/sites-available/` and symlinked to `/etc/nginx/sites-enabled/`.

### SSL Certificates
SSL certificates are managed using Certbot and stored in `/etc/letsencrypt/`.

### Database
- MariaDB/PostgreSQL databases are created per app.
- Credentials are stored in the SQLite database.

---

## 📋 Notes

- Ensure the server has a valid public IP.
- Use `ufw` to manage firewall rules.
- Backup your SQLite database regularly.
- Customize the landing page by editing `landing_template.html`.

---

## 🛡️ Security

- Passwords are generated randomly and stored securely.
- SFTP users are isolated to their respective directories.
- NGINX is configured with security headers.

---

## 📧 Support

For issues or feature requests, contact [support@sanmishatech.com](mailto:support@sanmishatech.com).

