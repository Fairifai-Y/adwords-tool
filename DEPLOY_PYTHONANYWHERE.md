# Deployment Guide: AdWords Tool op PythonAnywhere

## 📋 Stappenplan

### 1. **Project uploaden naar PythonAnywhere**

#### Optie A: Via Files tab (aanbevolen voor eerste keer)
1. Ga naar **Files** tab in PythonAnywhere dashboard
2. Navigeer naar `/home/SDeal/` (of je username)
3. Upload je hele `adwords-tool` folder:
   - Maak een nieuwe folder `adwords-tool` aan
   - Upload alle bestanden via de web interface
   - **BELANGRIJK**: Upload ook de `config/` folder met `google-ads.yaml`

#### Optie B: Via Git (als je Git gebruikt)
```bash
# In een Bash console op PythonAnywhere:
cd ~
git clone <jouw-repo-url> adwords-tool
cd adwords-tool
```

### 2. **Dependencies installeren**

Open een **Bash console** op PythonAnywhere en voer uit:

```bash
cd ~/adwords-tool
pip3.10 install --user -r requirements.txt
```

**Let op**: PythonAnywhere gebruikt Python 3.10 standaard. Als je Python 3.13 nodig hebt, moet je mogelijk upgraden naar een beta account of een andere Python versie gebruiken.

### 3. **Configuratie bestanden uploaden**

Zorg dat je `config/google-ads.yaml` bestand op PythonAnywhere staat:

```bash
# Check of het bestand er is:
ls -la ~/adwords-tool/config/google-ads.yaml
```

Als het bestand er niet is, upload het handmatig via de **Files** tab.

### 4. **Web App configureren**

1. Ga naar de **Web** tab in PythonAnywhere dashboard
2. Klik op **"Add a new web app"** (of bewerk een bestaande)
3. Kies **Flask** als framework
4. Kies **Python 3.10** (of de versie die je gebruikt)
5. **Source code**: `/home/SDeal/adwords-tool` (pas aan naar jouw username)
6. **Working directory**: `/home/SDeal/adwords-tool`
7. **WSGI configuration file**: Klik op de link om te bewerken

### 5. **WSGI configuratie aanpassen**

In de WSGI configuratie file, vervang de inhoud met:

```python
import sys
from pathlib import Path

# Add project root to path
project_root = Path('/home/SDeal/adwords-tool')  # Pas aan naar jouw pad!
sys.path.insert(0, str(project_root))

# Set environment variables
import os
os.environ["GOOGLE_ADS_CONFIGURATION_FILE"] = str(project_root / "config" / "google-ads.yaml")

# Import Flask app
from simple_web import app

application = app  # PythonAnywhere verwacht 'application'
```

**BELANGRIJK**: Vervang `/home/SDeal/` met jouw eigen username!

### 6. **Static files en templates**

PythonAnywhere serveert static files automatisch, maar check:

- **Static files mapping**: 
  - URL: `/static/`
  - Directory: `/home/SDeal/adwords-tool/static/` (als je static files hebt)

- **Templates**: Zorg dat `templates/` folder bestaat en toegankelijk is

### 7. **Environment variables (optioneel)**

Als je `.env` bestanden gebruikt, voeg ze toe via de **Web** tab → **Environment variables** sectie, of zet ze in de WSGI file:

```python
os.environ["DATABASE_URL"] = "postgresql://..."
os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"] = "..."
```

### 8. **Web app starten**

1. Ga naar **Web** tab
2. Klik op de groene **"Reload"** knop om de web app te herstarten
3. Je web app zou nu beschikbaar moeten zijn op: `https://SDeal.pythonanywhere.com` (of je custom domain)

### 9. **Testen**

Open je browser en ga naar:
- `https://SDeal.pythonanywhere.com` (of je custom domain)

Je zou nu de Google Ads Tools interface moeten zien!

## 🔧 Troubleshooting

### Probleem: "Module not found"
**Oplossing**: 
```bash
# Installeer dependencies opnieuw
cd ~/adwords-tool
pip3.10 install --user -r requirements.txt
```

### Probleem: "Config file not found"
**Oplossing**: 
- Check of `config/google-ads.yaml` bestaat: `ls -la ~/adwords-tool/config/`
- Check de WSGI file of het pad correct is

### Probleem: "Permission denied"
**Oplossing**: 
```bash
# Zorg dat bestanden leesbaar zijn
chmod -R 755 ~/adwords-tool
```

### Probleem: Subprocess calls werken niet
**Oplossing**: 
- De code gebruikt nu `sys.executable` in plaats van hardcoded paths
- Als het nog steeds niet werkt, check de **Error log** in de **Web** tab

### Probleem: Google Ads API errors
**Oplossing**: 
- Check of `config/google-ads.yaml` correct is geüpload
- Check of credentials geldig zijn
- Check de **Error log** voor details

## 📝 Belangrijke notities

1. **Python versie**: PythonAnywhere gebruikt standaard Python 3.10. Als je 3.13 nodig hebt, overweeg een beta account of upgrade.

2. **File paths**: Alle hardcoded Windows paths (`C:\Users\...`) zijn vervangen door `sys.executable` zodat het op elke platform werkt.

3. **Subprocess calls**: Scripts worden aangeroepen via `subprocess.run()` met `sys.executable`. Dit zou moeten werken op PythonAnywhere.

4. **Database**: Als je PostgreSQL gebruikt, moet je mogelijk een externe database service gebruiken (PythonAnywhere free accounts hebben geen PostgreSQL).

5. **Reports folder**: De `reports/` folder wordt automatisch aangemaakt. Check of de web app schrijfrechten heeft.

6. **Logs**: Check de **Error log** in de **Web** tab voor debugging informatie.

## 🚀 Volgende stappen

- Test alle functionaliteit in de web interface
- Check de error logs regelmatig
- Overweeg een custom domain als je het productief gebruikt
- Backup je `config/google-ads.yaml` regelmatig (bevat gevoelige credentials)

## 📞 Support

Als je problemen hebt:
1. Check de **Error log** in de **Web** tab
2. Check de **Server log** voor runtime errors
3. Test scripts handmatig in een **Bash console** om te zien of ze werken
