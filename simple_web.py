#!/usr/bin/env python3
"""
Simple Google Ads Tools Web Interface
"""
import os
import sys
import subprocess
import json
import shutil
from pathlib import Path

def get_python_executable():
    """Get the correct Python executable, handling PythonAnywhere uwsgi issue and Windows."""
    import platform
    
    # On PythonAnywhere, sys.executable points to uwsgi, so we MUST find python explicitly
    # On Windows, prefer 'py' launcher, then 'python'
    # On Linux/PythonAnywhere, prefer 'python3.10', then 'python3'
    
    if platform.system() == 'Windows':
        # Windows: try 'py', 'python', then sys.executable (if it's actually Python)
        for python_cmd in ['py', 'python']:
            if shutil.which(python_cmd):
                return python_cmd
        # Check if sys.executable is actually Python (not something else)
        if 'python' in sys.executable.lower() and 'uwsgi' not in sys.executable.lower():
            return sys.executable
    else:
        # Linux/PythonAnywhere: ALWAYS try to find python explicitly (never use sys.executable if it's uwsgi)
        # First try common paths directly (more reliable than shutil.which on some systems)
        common_paths = [
            '/usr/bin/python3.10',
            '/usr/local/bin/python3.10',
            '/usr/bin/python3',
            '/usr/local/bin/python3',
            '/bin/python3.10',
            '/bin/python3',
        ]
        for python_path in common_paths:
            if os.path.exists(python_path) and os.access(python_path, os.X_OK):
                return python_path
        
        # Then try shutil.which (might work if PATH is set correctly)
        for python_cmd in ['python3.10', 'python3', 'python']:
            found = shutil.which(python_cmd)
            if found:
                return found
        
        # If we're on Linux and sys.executable is NOT uwsgi, it might be OK
        if 'uwsgi' not in sys.executable.lower() and 'python' in sys.executable.lower():
            return sys.executable
    
    # Last resort: try to find any Python (cross-platform)
    for python_cmd in ['python3.10', 'python3', 'python', 'py']:
        found = shutil.which(python_cmd)
        if found:
            return found
    
    # Final fallback: only if sys.executable is NOT uwsgi
    if 'uwsgi' not in sys.executable.lower():
        return sys.executable
    
    # If we get here and sys.executable is uwsgi, we have a problem
    # Return a default that should work on most systems
    return 'python3'

# Try to import Flask, install if not available
try:
    from flask import Flask, render_template_string, request, jsonify, send_file
except ImportError:
    print("Flask not found. Installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
    from flask import Flask, render_template_string, request, jsonify, send_file

app = Flask(__name__)

# HTML template for the interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="nl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Google Ads Tools - SDeal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        .tool-card { border: none; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.1); margin-bottom: 30px; }
        .btn-primary { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border: none; border-radius: 25px; }
        .btn-success { background: linear-gradient(135deg, #56ab2f 0%, #a8e6cf 100%); border: none; border-radius: 25px; }
        .btn-warning { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); border: none; border-radius: 25px; }
        .result-box { background: #f8f9fa; border-radius: 10px; padding: 20px; margin-top: 20px; max-height: 400px; overflow-y: auto; }
        .label-checkbox { margin: 5px 0; }
        .label-checkbox input[type="checkbox"] { margin-right: 8px; }
        .preview-box { background: #e3f2fd; border: 1px solid #2196f3; border-radius: 10px; padding: 15px; margin-top: 15px; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container">
            <a class="navbar-brand" href="#top">SDeal Google Ads Tools</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#mainNavbar" aria-controls="mainNavbar" aria-expanded="false" aria-label="Toggle navigation">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="mainNavbar">
                <ul class="navbar-nav ms-auto">
                    <li class="nav-item">
                        <a class="nav-link" href="#section-labels">Labels & Campaigns</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="#section-pmax">PMax Creation</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/seller-clicks#section-seller-clicks">Seller Kliks</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/seller-performance">Seller ROAS</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="#section-roas">Portfolio ROAS</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="#section-pmax-roas">PMax ROAS</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="#section-cleanup">Cleanup</a>
                    </li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container mt-4" id="top">
        <h1 class="mb-3">Google Ads Campaign Tools</h1>
        
        <!-- Global account selector -->
        <div class="row mb-4">
            <div class="col-md-6">
                <label class="form-label">Account selectie</label>
                <select class="form-select" id="accountSelector">
                    <option value="">Kies account...</option>
                </select>
                <small class="text-muted">
                    Stelt automatisch Customer ID en Merchant Center ID in voor de formulieren hieronder.
                </small>
            </div>
        </div>
        
        <div class="row" id="section-labels">
            <!-- Label Discovery -->
            <div class="col-md-6">
                <div class="card tool-card">
                    <div class="card-header bg-primary text-white">
                        <h5 class="mb-0">Label Discovery</h5>
                    </div>
                    <div class="card-body">
                        <form id="discoverForm" onsubmit="event.preventDefault(); discoverLabels();">
                            <div class="mb-3">
                                <label class="form-label">Customer ID *</label>
                                <input type="text" class="form-control" id="customerId" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Label Index</label>
                                <select class="form-select" id="labelIndex">
                                    <option value="0">custom_label_0</option>
                                    <option value="1">custom_label_1</option>
                                    <option value="2">custom_label_2</option>
                                </select>
                            </div>

                            <div class="mb-3">
                                <label class="form-label">Merchant Center ID (optioneel)</label>
                                <input type="text" class="form-control" id="merchantId">
                            </div>
                            <div class="mb-3">
                                <div class="form-check">
                                    <input class="form-check-input" type="checkbox" id="extendedSearch">
                                    <label class="form-check-label" for="extendedSearch">
                                        Extended Search (90 dagen, ALLE labels inclusief zonder traffic)
                                    </label>
                                </div>
                            </div>
                            <button type="button" class="btn btn-primary" onclick="discoverLabels()">Discover Labels</button>
                        </form>
                        <div id="discoverResults" class="result-box" style="display: none;"></div>
                    </div>
                </div>
            </div>

            <!-- Campaign Creation -->
            <div class="col-md-6">
                <div class="card tool-card">
                    <div class="card-header bg-success text-white">
                        <h5 class="mb-0">Campaign Creation</h5>
                    </div>
                    <div class="card-body">
                        <form id="createForm">
                            <div class="mb-3">
                                <label class="form-label">Customer ID *</label>
                                <input type="text" class="form-control" id="createCustomerId" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Label Index</label>
                                <select class="form-select" id="createLabelIndex">
                                    <option value="0">custom_label_0</option>
                                    <option value="1">custom_label_1</option>
                                    <option value="2">custom_label_2</option>
                                </select>
                            </div>
                            <div class="mb-3">
                                <div class="alert alert-info">
                                    <strong>Standard Shopping Campagnes:</strong><br>
                                    Campagnes worden automatisch aangemaakt voor alle combinaties van custom_label_0 + custom_label_4 + custom_label_2.<br>
                                    Geen handmatige label selectie nodig.
                                </div>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Campaign Prefix</label>
                                <input type="text" class="form-control" id="campaignPrefix" value="" placeholder="Leave empty to search all ENABLED campaigns">
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Daily Budget (€)</label>
                                <input type="number" class="form-control" id="dailyBudget" value="5.0" step="0.1">
                            </div>
                            
                            <div class="mb-3">
                                <label for="roasFactor" class="form-label">ROAS Factor (±%)</label>
                                <div class="input-group">
                                    <span class="input-group-text">±</span>
                                    <input type="number" class="form-control" id="roasFactor" value="0" step="1" min="-50" max="50" placeholder="0">
                                    <span class="input-group-text">%</span>
                                </div>
                                <small class="form-text text-muted">
                                    Pas de berekende ROAS aan met percentage. Bijv: +10% maakt van 600 → 660, -10% maakt van 600 → 540
                                </small>
                            </div>
                            <div class="mb-3">
                                <div class="form-check">
                                    <input class="form-check-input" type="checkbox" id="startEnabled">
                                    <label class="form-check-label" for="startEnabled">
                                        <strong>Start campagnes direct (ENABLED)</strong>
                                    </label>
                                    <small class="form-text text-muted d-block">
                                        Als aangevinkt: campagnes beginnen direct met serveren. Anders: campagnes worden gepauzeerd aangemaakt.
                                    </small>
                                </div>
                            </div>
                            
                            <div class="mb-3">
                                <label class="form-label">Target Countries</label>
                                <div class="border rounded p-3" style="background: #f8f9fa;">
                                    <div class="row">
                                        <div class="col-md-4">
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="countryNL" value="NL" checked>
                                                <label class="form-check-label" for="countryNL">🇳🇱 Nederland (NL)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="countryBE" value="BE">
                                                <label class="form-check-label" for="countryBE">🇧🇪 België (BE)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="countryDE" value="DE">
                                                <label class="form-check-label" for="countryDE">🇩🇪 Duitsland (DE)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="countryFR" value="FR">
                                                <label class="form-check-label" for="countryFR">🇫🇷 Frankrijk (FR)</label>
                                            </div>
                                        </div>
                                        <div class="col-md-4">
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="countryDK" value="DK">
                                                <label class="form-check-label" for="countryDK">🇩🇰 Denemarken (DK)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="countryIT" value="IT">
                                                <label class="form-check-label" for="countryIT">🇮🇹 Italië (IT)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="countrySE" value="SE">
                                                <label class="form-check-label" for="countrySE">🇸🇪 Zweden (SE)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="countryPL" value="PL">
                                                <label class="form-check-label" for="countryPL">🇵🇱 Polen (PL)</label>
                                            </div>
                                        </div>
                                        <div class="col-md-4">
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="countryAT" value="AT">
                                                <label class="form-check-label" for="countryAT">🇦🇹 Oostenrijk (AT)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="countryCH" value="CH">
                                                <label class="form-check-label" for="countryCH">🇨🇭 Zwitserland (CH)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="countryES" value="ES">
                                                <label class="form-check-label" for="countryES">🇪🇸 Spanje (ES)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="countryGB" value="GB">
                                                <label class="form-check-label" for="countryGB">🇬🇧 Verenigd Koninkrijk (GB)</label>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="mt-2">
                                        <button type="button" class="btn btn-sm btn-outline-primary" onclick="selectAllCountries()">Alles selecteren</button>
                                        <button type="button" class="btn btn-sm btn-outline-secondary" onclick="deselectAllCountries()">Alles deselecteren</button>
                                    </div>
                                </div>
                            </div>

                            <div class="mb-3">
                                <label class="form-label">Target Languages</label>
                                <div class="border rounded p-3" style="background: #f8f9fa;">
                                    <div class="row">
                                        <div class="col-md-4">
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="langNL" value="nl" checked>
                                                <label class="form-check-label" for="langNL">🇳🇱 Nederlands (nl)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="langEN" value="en">
                                                <label class="form-check-label" for="langEN">🇬🇧 Engels (en)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="langDE" value="de">
                                                <label class="form-check-label" for="langDE">🇩🇪 Duits (de)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="langFR" value="fr">
                                                <label class="form-check-label" for="langFR">🇫🇷 Frans (fr)</label>
                                            </div>
                                        </div>
                                        <div class="col-md-4">
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="langDA" value="da">
                                                <label class="form-check-label" for="langDA">🇩🇰 Deens (da)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="langIT" value="it">
                                                <label class="form-check-label" for="langIT">🇮🇹 Italiaans (it)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="langSV" value="sv">
                                                <label class="form-check-label" for="langSV">🇸🇪 Zweeds (sv)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="langPL" value="pl">
                                                <label class="form-check-label" for="langPL">🇵🇱 Pools (pl)</label>
                                            </div>
                                        </div>
                                        <div class="col-md-4">
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="langES" value="es">
                                                <label class="form-check-label" for="langES">🇪🇸 Spaans (es)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="langPT" value="pt">
                                                <label class="form-check-label" for="langPT">🇵🇹 Portugees (pt)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="langRU" value="ru">
                                                <label class="form-check-label" for="langRU">🇷🇺 Russisch (ru)</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="langCS" value="cs">
                                                <label class="form-check-label" for="langCS">🇨🇿 Tsjechisch (cs)</label>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="mt-2">
                                        <button type="button" class="btn btn-sm btn-outline-primary" onclick="selectAllLanguages()">Alles selecteren</button>
                                        <button type="button" class="btn btn-sm btn-outline-secondary" onclick="deselectAllLanguages()">Alles deselecteren</button>
                                    </div>
                                </div>
                            </div>

                            <div class="mb-3">
                                <label class="form-label">Feed Label</label>
                                <select class="form-select" id="feedLabel">
                                    <option value="nl">🇳🇱 Nederlands (nl)</option>
                                    <option value="">-- Selecteer feed label --</option>
                                    <option value="be">🇧🇪 Belgisch (be)</option>
                                    <option value="de">🇩🇪 Duits (de)</option>
                                    <option value="fr">🇫🇷 Frans (fr)</option>
                                    <option value="dk">🇩🇰 Deens (dk)</option>
                                    <option value="it">🇮🇹 Italiaans (it)</option>
                                    <option value="se">🇸🇪 Zweeds (se)</option>
                                    <option value="pl">🇵🇱 Pools (pl)</option>
                                    <option value="at">🇦🇹 Oostenrijks (at)</option>
                                    <option value="ch">🇨🇭 Zwitsers (ch)</option>
                                    <option value="es">🇪🇸 Spaans (es)</option>
                                    <option value="gb">🇬🇧 Brits (gb)</option>
                                    <option value="custom">📝 Aangepast...</option>
                                </select>
                                <div id="customFeedLabelDiv" style="display: none;" class="mt-2">
                                    <input type="text" class="form-control" id="customFeedLabel" placeholder="Voer aangepaste feed label in">
                                </div>
                                <small class="form-text text-muted">
                                    Selecteer het land-specifieke feed label uit Merchant Center
                                </small>
                            </div>

                            <div class="mb-3" id="merchantIdGroup">
                                <label class="form-label">Merchant Center ID *</label>
                                <input type="text" class="form-control" id="merchantIdCreate" required>
                                <small class="text-muted">Vereist voor Standard Shopping campagnes. Vind je Merchant Center ID in Google Ads onder Tools > Linked accounts > Merchant Center.</small>
                            </div>
                            <button type="button" class="btn btn-warning me-2" onclick="previewCampaigns()">Preview Campagnes</button>
                            <button type="submit" class="btn btn-success" id="createButton">Create Selected Campaigns</button>
                            
                            <!-- Progress Bar -->
                            <div id="progressContainer" class="mt-3" style="display: none;">
                                <div class="progress" style="height: 25px;">
                                    <div id="progressBar" class="progress-bar progress-bar-striped progress-bar-animated" 
                                         role="progressbar" style="width: 0%" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">
                                        <span id="progressText">Initializing...</span>
                                    </div>
                                </div>
                                <div class="mt-2">
                                    <small id="progressDetails" class="text-muted">Preparing campaign creation...</small>
                                </div>
                            </div>
                        </form>
                        <div id="previewResults" class="preview-box" style="display: none;"></div>
                        <div id="createResults" class="result-box" style="display: none;"></div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- PMax Creation -->
        <div class="row mt-4" id="section-pmax">
            <div class="col-12">
                <div class="card tool-card">
                    <div class="card-header bg-info text-white">
                        <h5 class="mb-0">🚀 PMax Creation</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6>[CREATE] PMax ALL Labels</h6>
                                <p class="text-muted">Automatisch PMax campagnes voor ALLE ontdekte labels. Geen handmatige label selectie nodig - alle labels worden automatisch gebruikt.</p>
                                
                                <div class="mb-3">
                                    <label class="form-label">Customer ID *</label>
                                    <input type="text" class="form-control" id="pmaxCustomerId" required>
                                </div>
                                
                                <div class="mb-3">
                                    <label class="form-label">Label Index</label>
                                    <select class="form-select" id="pmaxLabelIndex">
                                        <option value="0">custom_label_0</option>
                                        <option value="1">custom_label_1</option>
                                        <option value="2">custom_label_2</option>
                                    </select>
                                </div>
                                
                                <div class="mb-3">
                                    <label class="form-label">PMax Type</label>
                                    <select class="form-select" id="pmaxTypeSelect">
                                        <option value="feed-only">Feed-Only PMax (Producten uit Merchant Center)</option>
                                        <option value="normal">Normale PMax (Met creatives)</option>
                                    </select>
                                    <small class="text-muted">
                                        <strong>Feed-Only:</strong> Alleen producten uit Merchant Center feed, vereist Merchant Center ID<br>
                                        <strong>Normale PMax:</strong> Kan creatives hebben, Merchant Center ID optioneel
                                    </small>
                                </div>
                                
                                <div class="mb-3" id="pmaxMerchantIdGroup">
                                    <label class="form-label">Merchant Center ID *</label>
                                    <input type="text" class="form-control" id="pmaxMerchantId" required>
                                    <small class="text-muted">Vereist voor Feed-Only PMax. Vind je Merchant Center ID in Google Ads onder Tools > Linked accounts > Merchant Center.</small>
                                </div>
                                
                                <div class="mb-3">
                                    <label class="form-label">Campaign Prefix</label>
                                    <input type="text" class="form-control" id="pmaxPrefix" value="PMax ALL" placeholder="PMax ALL">
                                </div>
                                
                                <div class="mb-3">
                                    <label class="form-label">Daily Budget (€)</label>
                                    <input type="number" class="form-control" id="pmaxDailyBudget" value="5.0" step="0.1">
                                </div>
                                
                                <div class="mb-3">
                                    <label for="pmaxRoasFactor" class="form-label">ROAS Factor (±%)</label>
                                    <div class="input-group">
                                        <span class="input-group-text">±</span>
                                        <input type="number" class="form-control" id="pmaxRoasFactor" value="0" step="1" min="-50" max="50" placeholder="0">
                                        <span class="input-group-text">%</span>
                                    </div>
                                    <small class="form-text text-muted">
                                        Pas de berekende ROAS aan met percentage. Bijv: +10% maakt van 600 → 660, -10% maakt van 600 → 540
                                    </small>
                                </div>
                                
                                <div class="mb-3">
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" id="pmaxStartEnabled">
                                        <label class="form-check-label" for="pmaxStartEnabled">
                                            <strong>Start campagnes direct (ENABLED)</strong>
                                        </label>
                                        <small class="form-text text-muted d-block">
                                            Als aangevinkt: campagnes beginnen direct met serveren. Anders: campagnes worden gepauzeerd aangemaakt.
                                        </small>
                                    </div>
                                </div>
                                
                                <div class="mb-3">
                                    <label class="form-label">Target Countries</label>
                                    <div class="border rounded p-3" style="background: #f8f9fa;">
                                        <div class="row">
                                            <div class="col-md-4">
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxCountryNL" value="NL" checked>
                                                    <label class="form-check-label" for="pmaxCountryNL">🇳🇱 Nederland (NL)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxCountryBE" value="BE">
                                                    <label class="form-check-label" for="pmaxCountryBE">🇧🇪 België (BE)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxCountryDE" value="DE">
                                                    <label class="form-check-label" for="pmaxCountryDE">🇩🇪 Duitsland (DE)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxCountryFR" value="FR">
                                                    <label class="form-check-label" for="pmaxCountryFR">🇫🇷 Frankrijk (FR)</label>
                                                </div>
                                            </div>
                                            <div class="col-md-4">
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxCountryDK" value="DK">
                                                    <label class="form-check-label" for="pmaxCountryDK">🇩🇰 Denemarken (DK)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxCountryIT" value="IT">
                                                    <label class="form-check-label" for="pmaxCountryIT">🇮🇹 Italië (IT)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxCountrySE" value="SE">
                                                    <label class="form-check-label" for="pmaxCountrySE">🇸🇪 Zweden (SE)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxCountryPL" value="PL">
                                                    <label class="form-check-label" for="pmaxCountryPL">🇵🇱 Polen (PL)</label>
                                                </div>
                                            </div>
                                            <div class="col-md-4">
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxCountryAT" value="AT">
                                                    <label class="form-check-label" for="pmaxCountryAT">🇦🇹 Oostenrijk (AT)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxCountryCH" value="CH">
                                                    <label class="form-check-label" for="pmaxCountryCH">🇨🇭 Zwitserland (CH)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxCountryES" value="ES">
                                                    <label class="form-check-label" for="pmaxCountryES">🇪🇸 Spanje (ES)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxCountryGB" value="GB">
                                                    <label class="form-check-label" for="pmaxCountryGB">🇬🇧 Verenigd Koninkrijk (GB)</label>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="mt-2">
                                            <button type="button" class="btn btn-sm btn-outline-primary" onclick="selectAllPmaxCountries()">Alles selecteren</button>
                                            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="deselectAllPmaxCountries()">Alles deselecteren</button>
                                        </div>
                                    </div>
                                </div>

                                <div class="mb-3">
                                    <label class="form-label">Target Languages</label>
                                    <div class="border rounded p-3" style="background: #f8f9fa;">
                                        <div class="row">
                                            <div class="col-md-4">
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxLangNL" value="nl" checked>
                                                    <label class="form-check-label" for="pmaxLangNL">🇳🇱 Nederlands (nl)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxLangEN" value="en">
                                                    <label class="form-check-label" for="pmaxLangEN">🇬🇧 Engels (en)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxLangDE" value="de">
                                                    <label class="form-check-label" for="pmaxLangDE">🇩🇪 Duits (de)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxLangFR" value="fr">
                                                    <label class="form-check-label" for="pmaxLangFR">🇫🇷 Frans (fr)</label>
                                                </div>
                                            </div>
                                            <div class="col-md-4">
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxLangDA" value="da">
                                                    <label class="form-check-label" for="pmaxLangDA">🇩🇰 Deens (da)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxLangIT" value="it">
                                                    <label class="form-check-label" for="pmaxLangIT">🇮🇹 Italiaans (it)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxLangSV" value="sv">
                                                    <label class="form-check-label" for="pmaxLangSV">🇸🇪 Zweeds (sv)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxLangPL" value="pl">
                                                    <label class="form-check-label" for="pmaxLangPL">🇵🇱 Pools (pl)</label>
                                                </div>
                                            </div>
                                            <div class="col-md-4">
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxLangES" value="es">
                                                    <label class="form-check-label" for="pmaxLangES">🇪🇸 Spaans (es)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxLangPT" value="pt">
                                                    <label class="form-check-label" for="pmaxLangPT">🇵🇹 Portugees (pt)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxLangRU" value="ru">
                                                    <label class="form-check-label" for="pmaxLangRU">🇷🇺 Russisch (ru)</label>
                                                </div>
                                                <div class="form-check">
                                                    <input class="form-check-input" type="checkbox" id="pmaxLangCS" value="cs">
                                                    <label class="form-check-label" for="pmaxLangCS">🇨🇿 Tsjechisch (cs)</label>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="mt-2">
                                            <button type="button" class="btn btn-sm btn-outline-primary" onclick="selectAllPmaxLanguages()">Alles selecteren</button>
                                            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="deselectAllPmaxLanguages()">Alles deselecteren</button>
                                        </div>
                                    </div>
                                </div>
                                
                                <div class="mb-3">
                                    <label class="form-label">Feed Label</label>
                                    <select class="form-select" id="pmaxFeedLabel">
                                        <option value="nl">🇳🇱 Nederlands (nl)</option>
                                        <option value="">-- Selecteer feed label --</option>
                                        <option value="be">🇧🇪 Belgisch (be)</option>
                                        <option value="de">🇩🇪 Duits (de)</option>
                                        <option value="fr">🇫🇷 Frans (fr)</option>
                                        <option value="dk">🇩🇰 Deens (dk)</option>
                                        <option value="it">🇮🇹 Italiaans (it)</option>
                                        <option value="se">🇸🇪 Zweeds (se)</option>
                                        <option value="pl">🇵🇱 Pools (pl)</option>
                                        <option value="at">🇦🇹 Oostenrijks (at)</option>
                                        <option value="ch">🇨🇭 Zwitsers (ch)</option>
                                        <option value="es">🇪🇸 Spaans (es)</option>
                                        <option value="gb">🇬🇧 Brits (gb)</option>
                                        <option value="custom">📝 Aangepast...</option>
                                    </select>
                                    <div id="pmaxCustomFeedLabelDiv" style="display: none;" class="mt-2">
                                        <input type="text" class="form-control" id="pmaxCustomFeedLabel" placeholder="Voer aangepaste feed label in">
                                    </div>
                                    <small class="form-text text-muted">
                                        Selecteer het land-specifieke feed label uit Merchant Center
                                    </small>
                                </div>
                                
                                <button type="button" class="btn btn-warning me-2" onclick="previewPmaxCampaigns()">Preview PMax Campagnes</button>
                                <button type="button" class="btn btn-info" onclick="createPmaxCampaigns()">Create PMax Campagnes</button>
                            </div>
                            
                            <div class="col-md-6">
                                <h6>[RESULTS] PMax Creation Results</h6>
                                <div id="pmaxResults" class="border rounded p-3" style="background: #f8f9fa; min-height: 200px;">
                                    <small class="text-muted">Klik op "Preview PMax Campagnes" of "Create PMax Campagnes" om te beginnen...</small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Weekly Campaign Monitor -->
        <div class="row mt-4">
            <div class="col-12">
                <div class="card tool-card">
                    <div class="card-header bg-warning text-dark">
                        <h5 class="mb-0">📅 Weekly Campaign Monitor</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6>[ANALYSIS] Campaign Analysis</h6>
                                <p class="text-muted">Controleer bestaande campagnes en ontdek nieuwe labels die campagnes nodig hebben.</p>
                                
                                <div class="mb-3">
                                    <label class="form-label">Customer ID *</label>
                                    <input type="text" class="form-control" id="monitorCustomerId" placeholder="866-851-6809">
                                </div>
                                
                                <div class="mb-3">
                                    <label class="form-label">Campaign Prefix</label>
                                    <input type="text" class="form-control" id="monitorPrefix" value="" placeholder="Leave empty to search all ENABLED campaigns">
                                </div>
                                
                                <div class="mb-3">
                                    <label class="form-label">Label Index</label>
                                    <select class="form-select" id="monitorLabelIndex">
                                        <option value="0">custom_label_0</option>
                                        <option value="1">custom_label_1</option>
                                        <option value="2">custom_label_2</option>
                                    </select>
                                </div>
                                
                                <div class="mb-3">
                                    <label class="form-label">Performance Threshold</label>
                                    <div class="row">
                                        <div class="col-6">
                                            <input type="number" class="form-control" id="minImpressions" value="100" placeholder="Min impressions">
                                        </div>
                                        <div class="col-6">
                                            <input type="number" class="form-control" id="minConversions" value="0" placeholder="Min conversions">
                                        </div>
                                    </div>
                                    <small class="text-muted">Campagnes onder deze drempel worden als 'leeg' beschouwd</small>
                                </div>
                                
                                <div class="mb-3">
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" id="autoPauseEmpty">
                                        <label class="form-check-label" for="autoPauseEmpty">
                                            Automatisch lege campagnes pauzeren
                                        </label>
                                    </div>
                                </div>
                                
                                <button type="button" class="btn btn-warning" onclick="runWeeklyMonitor()">
                                    [RUN] Run Weekly Monitor
                                </button>
                                
                                <div class="mt-3">
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" id="detailedReport" checked>
                                        <label class="form-check-label" for="detailedReport">
                                            📊 Generate Detailed Performance Report
                                        </label>
                                    </div>
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" id="exportCsv">
                                        <label class="form-check-label" for="exportCsv">
                                            📥 Export Report to CSV
                                        </label>
                                    </div>
                                </div>
                                
                                <div class="mt-3">
                                    <h6>📈 Performance Metrics to Include:</h6>
                                    <div class="row">
                                        <div class="col-md-6">
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="includeROAS" checked>
                                                <label class="form-check-label" for="includeROAS">ROAS & ROI Analysis</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="includeCTR" checked>
                                                <label class="form-check-label" for="includeCTR">CTR & CPC Analysis</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="includeBudget" checked>
                                                <label class="form-check-label" for="includeBudget">Budget Utilization</label>
                                            </div>
                                        </div>
                                        <div class="col-md-6">
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="includeVolume" checked>
                                                <label class="form-check-label" for="includeVolume">Volume Analysis</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="includeLabels" checked>
                                                <label class="form-check-label" for="includeLabels">Label Performance</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" id="includeTrends" checked>
                                                <label class="form-check-label" for="includeTrends">Performance Trends</label>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="col-md-6">
                                <h6>[RESULTS] Monitor Results</h6>
                                <div id="monitorResults" class="border rounded p-3" style="background: #f8f9fa; min-height: 200px;">
                                    <small class="text-muted">Klik op "Run Weekly Monitor" om te beginnen...</small>
                                </div>
                                
                                <div class="mt-3">
                                    <button type="button" class="btn btn-success" id="applyChangesBtn" style="display: none;" onclick="applyWeeklyChanges()">
                                        [APPLY] Apply Changes
                                    </button>
                                    <button type="button" class="btn btn-info" id="viewDetailsBtn" style="display: none;" onclick="viewWeeklyChanges()">
                                        [DETAILS] View Details
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Portfolio ROAS Adjustment -->
        <div class="row mt-4" id="section-roas">
            <div class="col-12">
                <div class="card tool-card">
                    <div class="card-header bg-info text-white">
                        <h5 class="mb-0">🎯 Portfolio ROAS Adjustment</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6>[ADJUST] Adjust All tROAS Strategies</h6>
                                <p class="text-muted">Pas de ROAS aan voor alle portfolio TARGET_ROAS strategies met "tROAS" in de naam.</p>
                                
                                <form id="adjustRoasForm" onsubmit="event.preventDefault(); adjustPortfolioRoas();">
                                    <div class="mb-3">
                                        <label class="form-label">Customer ID *</label>
                                        <input type="text" class="form-control" id="adjustRoasCustomerId" required placeholder="123-456-7890">
                                    </div>
                                    
                                    <div class="mb-3">
                                        <div class="form-check mb-2">
                                            <input class="form-check-input" type="checkbox" id="adjustRoasReset">
                                            <label class="form-check-label" for="adjustRoasReset">
                                                <strong>Eerst resetten naar standaard waarde (op basis van seller marge)</strong>
                                            </label>
                                        </div>
                                        <small class="form-text text-muted d-block mb-2">
                                            Reset alle strategies naar standaard tROAS berekend uit custom_label_1 (marge) per seller. Daarna wordt het percentage (hieronder) toegepast.
                                        </small>
                                    </div>
                                    
                                    <div class="mb-3">
                                        <label class="form-label">Percentage Aanpassing (±%)</label>
                                        <div class="input-group">
                                            <span class="input-group-text">±</span>
                                            <input type="number" class="form-control" id="adjustRoasPercentage" step="1" min="-50" max="50" placeholder="0" value="0">
                                            <span class="input-group-text">%</span>
                                        </div>
                                        <small class="form-text text-muted">
                                            Zonder reset: percentage op huidige ROAS. Met reset: eerst naar standaard (marge), dan ±% daarop (bijv. reset + 10%).
                                        </small>
                                    </div>
                                    
                                    <div class="mb-3">
                                        <div class="form-check">
                                            <input class="form-check-input" type="checkbox" id="adjustRoasApply">
                                            <label class="form-check-label" for="adjustRoasApply">
                                                <strong>Apply Changes (anders preview/dry-run)</strong>
                                            </label>
                                        </div>
                                    </div>
                                    
                                    <button type="submit" class="btn btn-primary">
                                        [PREVIEW/APPLY] Adjust Portfolio ROAS
                                    </button>
                                </form>
                            </div>
                            
                            <div class="col-md-6">
                                <h6>[RESULTS] Adjustment Results</h6>
                                <div id="adjustRoasResults" class="border rounded p-3" style="background: #f8f9fa; min-height: 200px;">
                                    <small class="text-muted">Vul het formulier in en klik op "Adjust Portfolio ROAS" om te beginnen...</small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- PMax ROAS Adjustment -->
        <div class="row mt-4" id="section-pmax-roas">
            <div class="col-12">
                <div class="card tool-card">
                    <div class="card-header bg-success text-white">
                        <h5 class="mb-0">🚀 PMax ROAS Adjustment</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6>[ADJUST] Adjust PMax Campaign ROAS</h6>
                                <p class="text-muted">Pas de ROAS aan voor PMax campagnes die target_roas direct in de campagne hebben ingesteld (geen portfolio strategies).</p>
                                
                                <form id="adjustPmaxRoasForm" onsubmit="event.preventDefault(); adjustPmaxRoas();">
                                    <div class="mb-3">
                                        <label class="form-label">Customer ID *</label>
                                        <input type="text" class="form-control" id="adjustPmaxRoasCustomerId" required placeholder="123-456-7890">
                                    </div>
                                    
                                    <div class="mb-3">
                                        <label class="form-label">Campaign Prefix (optioneel)</label>
                                        <input type="text" class="form-control" id="adjustPmaxRoasPrefix" placeholder="Bijv. 'PMax ALL' (laat leeg voor alle PMax campagnes)">
                                        <small class="form-text text-muted">
                                            Filter op campagnes met dit prefix. Laat leeg om alle PMax campagnes met target_roas aan te passen.
                                        </small>
                                    </div>
                                    
                                    <div class="mb-3">
                                        <div class="form-check mb-2">
                                            <input class="form-check-input" type="checkbox" id="adjustPmaxRoasReset">
                                            <label class="form-check-label" for="adjustPmaxRoasReset">
                                                <strong>Eerst resetten naar standaard waarde (op basis van seller marge)</strong>
                                            </label>
                                        </div>
                                        <small class="form-text text-muted d-block mb-2">
                                            Reset alle campagnes naar standaard tROAS berekend uit custom_label_1 (marge) per seller. Daarna wordt het percentage (hieronder) toegepast.
                                        </small>
                                    </div>
                                    
                                    <div class="mb-3">
                                        <label class="form-label">Percentage Aanpassing (±%)</label>
                                        <div class="input-group">
                                            <span class="input-group-text">±</span>
                                            <input type="number" class="form-control" id="adjustPmaxRoasPercentage" step="1" min="-50" max="50" placeholder="0" value="0">
                                            <span class="input-group-text">%</span>
                                        </div>
                                        <small class="form-text text-muted">
                                            Zonder reset: percentage op huidige ROAS. Met reset: eerst naar standaard (marge), dan ±% daarop (bijv. reset + 10%).
                                        </small>
                                    </div>
                                    
                                    <div class="mb-3">
                                        <div class="form-check">
                                            <input class="form-check-input" type="checkbox" id="adjustPmaxRoasApply">
                                            <label class="form-check-label" for="adjustPmaxRoasApply">
                                                <strong>Apply Changes (anders preview/dry-run)</strong>
                                            </label>
                                        </div>
                                        <small class="form-text text-muted">
                                            Als niet aangevinkt: alleen preview (geen wijzigingen). Als aangevinkt: wijzigingen worden daadwerkelijk doorgevoerd.
                                        </small>
                                    </div>
                                    
                                    <button type="submit" class="btn btn-success">
                                        [PREVIEW/APPLY] Adjust PMax ROAS
                                    </button>
                                </form>
                            </div>
                            
                            <div class="col-md-6">
                                <h6>[RESULTS] PMax ROAS Adjustment Results</h6>
                                <div id="adjustPmaxRoasResults" class="border rounded p-3" style="background: #f8f9fa; min-height: 200px;">
                                    <small class="text-muted">Vul het formulier in en klik op "Adjust PMax ROAS" om te beginnen...</small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Seller Clicks Timeseries (last N days) -->
        <div class="row mt-4" id="section-seller-clicks">
            <div class="col-12">
                <div class="card tool-card">
                    <div class="card-header bg-info text-white">
                        <h5 class="mb-0">📈 Seller Klik-analyse (per dag, laatste N dagen)</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6>[ANALYSE] Kliks per dag voor een campagnenaam</h6>
                                <p class="text-muted">
                                    Haal een tijdreeks op met impressies, kliks, conversies, waarde en kosten per dag voor alle campagnes
                                    waarvan de naam een bepaalde tekst bevat (bijv. <code>EchtVeelVoorWeinig</code>).<br>
                                    Later kan deze filter eenvoudig worden omgezet naar een seller ID.
                                </p>
                                
                                <form id="sellerClicksForm" onsubmit="event.preventDefault(); fetchSellerClicksTimeseries();">
                                    <div class="mb-3">
                                        <label class="form-label">Customer ID *</label>
                                        <input type="text" class="form-control" id="sellerClicksCustomerId" required placeholder="123-456-7890">
                                    </div>

                                    <div class="mb-3">
                                        <label class="form-label">Campagnenaam (substring) *</label>
                                        <input type="text" class="form-control" id="sellerClicksCampaignName" required placeholder="EchtVeelVoorWeinig">
                                        <small class="form-text text-muted">
                                            We zoeken naar campagnes waarvan de naam deze tekst bevat (hoofdlettergevoelig zoals in Google Ads).
                                        </small>
                                    </div>

                                    <div class="mb-3">
                                        <label class="form-label">Dagen terug</label>
                                        <input type="number" class="form-control" id="sellerClicksDays" value="90" min="1" max="365">
                                    </div>

                                    <div class="mb-3">
                                        <div class="form-check">
                                            <input class="form-check-input" type="checkbox" id="sellerClicksExportCsv">
                                            <label class="form-check-label" for="sellerClicksExportCsv">
                                                Exporteer ook naar CSV (map <code>reports/</code> in dit project)
                                            </label>
                                        </div>
                                    </div>

                                    <button type="submit" class="btn btn-primary">
                                        [RUN] Seller Klik-analyse
                                    </button>
                                </form>
                            </div>

                            <div class="col-md-6">
                                <h6>[RESULTS] Seller Kliks per Dag</h6>
                                <div id="sellerClicksResults" class="border rounded p-3" style="background: #f8f9fa; min-height: 200px;">
                                    <small class="text-muted">
                                        Vul het formulier in en klik op "Seller Klik-analyse" om de tijdreeks per dag te zien.
                                    </small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Delete Inactive Campaigns -->
        <div class="row mt-4" id="section-cleanup">
            <div class="col-12">
                <div class="card tool-card">
                    <div class="card-header bg-danger text-white">
                        <h5 class="mb-0">🗑️ Delete Inactive Campaigns</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6>[CLEANUP] Verwijder inactieve campagnes</h6>
                                <p class="text-muted">
                                    Verwijder Shopping & PMax campagnes zonder impressies in de laatste X dagen. 
                                    Bijbehorende portfolio biedstrategieën worden alleen gerapporteerd en niet automatisch verwijderd.
                                </p>

                                <form id="deleteInactiveForm" onsubmit="event.preventDefault(); deleteInactiveCampaigns();">
                                    <div class="mb-3">
                                        <label class="form-label">Customer ID *</label>
                                        <input type="text" class="form-control" id="deleteInactiveCustomerId" required placeholder="123-456-7890">
                                    </div>

                                    <div class="mb-3">
                                        <label class="form-label">Dagen zonder impressies</label>
                                        <input type="number" class="form-control" id="deleteInactiveDays" value="60" min="7" step="1">
                                        <small class="form-text text-muted">
                                            Campagnes met 0 impressies in de laatste X dagen worden geselecteerd (Shopping & PMax, status ENABLED/PAUSED).
                                        </small>
                                    </div>

                                    <div class="mb-3">
                                        <div class="form-check">
                                            <input class="form-check-input" type="checkbox" id="deleteInactiveApply">
                                            <label class="form-check-label" for="deleteInactiveApply">
                                                <strong>Apply Deletions (anders alleen preview/dry-run)</strong>
                                            </label>
                                        </div>
                                    </div>

                                    <button type="submit" class="btn btn-danger">
                                        [PREVIEW/APPLY] Delete Inactive Campaigns
                                    </button>
                                </form>
                            </div>

                            <div class="col-md-6">
                                <h6>[RESULTS] Cleanup Results</h6>
                                <div id="deleteInactiveResults" class="border rounded p-3" style="background: #f8f9fa; min-height: 200px;">
                                    <small class="text-muted">Vul het formulier in en klik op "Delete Inactive Campaigns" om te beginnen...</small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let discoveredLabels = [];
        let accountsConfig = [];
        
        async function loadAccountsConfig() {
            try {
                const response = await fetch('/api/accounts');
                const result = await response.json();
                if (!result.success) {
                    console.warn('Failed to load accounts config:', result.error);
                    return;
                }
                accountsConfig = result.accounts || [];
                const select = document.getElementById('accountSelector');
                if (!select) return;
                
                accountsConfig.forEach(acc => {
                    const option = document.createElement('option');
                    const label = acc.label || acc.key;
                    const country = acc.country ? ` (${acc.country})` : '';
                    option.value = acc.key;
                    option.textContent = `${label}${country}`;
                    select.appendChild(option);
                });
                
                select.addEventListener('change', () => {
                    const key = select.value;
                    const acc = accountsConfig.find(a => a.key === key);
                    if (!acc) return;
                    
                    const primaryCustomerId = (acc.customer_ids && acc.customer_ids[0]) || '';
                    const merchantId = acc.merchant_id || '';
                    
                    const customerFields = [
                        'customerId',
                        'createCustomerId',
                        'pmaxCustomerId',
                        'sellerClicksCustomerId',
                        'adjustRoasCustomerId',
                        'deleteInactiveCustomerId'
                    ];
                    customerFields.forEach(id => {
                        const el = document.getElementById(id);
                        if (el && primaryCustomerId) {
                            el.value = primaryCustomerId;
                        }
                    });
                    
                    const merchantFields = [
                        'merchantId',
                        'merchantIdCreate',
                        'pmaxMerchantId'
                    ];
                    merchantFields.forEach(id => {
                        const el = document.getElementById(id);
                        if (el && merchantId) {
                            el.value = merchantId;
                        }
                    });
                });
            } catch (e) {
                console.warn('Error loading accounts config:', e);
            }
        }
        
        document.addEventListener('DOMContentLoaded', () => {
            loadAccountsConfig();
        });
        
        // Handle PMax type change (for PMax Creation section)
        document.getElementById('pmaxTypeSelect').addEventListener('change', function() {
            const pmaxType = this.value;
            const merchantIdGroup = document.getElementById('pmaxMerchantIdGroup');
            const merchantIdInput = document.getElementById('pmaxMerchantId');
            const label = merchantIdGroup.querySelector('label');
            const small = merchantIdGroup.querySelector('small');
            
            if (pmaxType === 'feed-only') {
                label.textContent = 'Merchant Center ID *';
                merchantIdInput.required = true;
                small.innerHTML = 'Vereist voor Feed-Only PMax. Vind je Merchant Center ID in Google Ads onder Tools > Linked accounts > Merchant Center.';
            } else {
                label.textContent = 'Merchant Center ID (optioneel)';
                merchantIdInput.required = false;
                small.innerHTML = 'Optioneel voor Normale PMax. Kan leeg blijven als je geen Merchant Center gebruikt.';
            }
        });
        
        // Handle feed label custom option (for PMax Creation section)
        document.getElementById('pmaxFeedLabel').addEventListener('change', function() {
            const feedLabel = this.value;
            const customDiv = document.getElementById('pmaxCustomFeedLabelDiv');
            if (feedLabel === 'custom') {
                customDiv.style.display = 'block';
            } else {
                customDiv.style.display = 'none';
            }
        });
        
        // Label Discovery
        document.getElementById('discoverForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = {
                customer_id: document.getElementById('customerId').value,
                label_index: parseInt(document.getElementById('labelIndex').value),
                merchant_id: document.getElementById('merchantId').value || null,
                extended_search: document.getElementById('extendedSearch').checked
            };

            try {
                const response = await fetch('/api/discover-labels', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(formData)
                });
                const result = await response.json();
                
                const container = document.getElementById('discoverResults');
                if (result.success) {
                    container.innerHTML = '<div class="alert alert-success"><h6>Labels gevonden:</h6><pre>' + result.output + '</pre><hr><small>Command: ' + (result.command || 'N/A') + '</small></div>';
                    
                    // Parse labels from output and store them
                    discoveredLabels = parseLabelsFromOutput(result.output);
                    updateLabelSelection();
                    
                    // Auto-fill Customer ID in creation form
                    document.getElementById('createCustomerId').value = formData.customer_id;
                    if (formData.merchant_id) {
                        document.getElementById('merchantIdCreate').value = formData.merchant_id;
                    }
                } else {
                    container.innerHTML = '<div class="alert alert-danger"><h6>Error:</h6><pre>' + (result.error || result.output) + '</pre><hr><small>Command: ' + (result.command || 'N/A') + '</small></div>';
                }
                container.style.display = 'block';
            } catch (error) {
                alert('Error: ' + error.message);
            }
        });

        // Campaign Creation
        document.getElementById('createForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            // Campaign creation now only supports Standard Shopping (product-type)
            const campaignType = 'product-type';
            
            const customerId = document.getElementById('createCustomerId').value.trim();
            if (!customerId) {
                alert('Vul een Customer ID in.');
                return;
            }
            
            const merchantId = document.getElementById('merchantIdCreate').value.trim();
            if (!merchantId) {
                alert('Vul een Merchant Center ID in. Dit is vereist voor Standard Shopping campagnes.');
                return;
            }
            
            console.log('Campaign type:', campaignType); // Debug log
            console.log('Customer ID for creation:', customerId); // Debug log
            
            // Show progress bar and disable button
            showProgressBar();
            disableCreateButton();
            
            const formData = {
                customer_id: customerId,
                campaign_type: campaignType,
                label_index: parseInt(document.getElementById('createLabelIndex').value),
                merchant_id: merchantId,
                prefix: document.getElementById('campaignPrefix').value,
                daily_budget: parseFloat(document.getElementById('dailyBudget').value),
                roas_factor: parseFloat(document.getElementById('roasFactor').value) || 0,
                start_enabled: document.getElementById('startEnabled').checked,
                target_languages: getSelectedLanguages().join(','),
                target_countries: getSelectedCountries().join(','),
                feed_label: getFeedLabel()
            };

            try {
                updateProgress(10, 'Versturen van campagne data...');
                
                const response = await fetch('/api/create-campaigns', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(formData)
                });
                
                updateProgress(50, 'Campagnes worden aangemaakt...');
                
                const result = await response.json();
                
                updateProgress(90, 'Resultaten worden verwerkt...');
                
                const container = document.getElementById('createResults');
                if (result.success) {
                    container.innerHTML = '<div class="alert alert-success"><h6>✅ Campagnes aangemaakt:</h6><pre>' + result.output + '</pre><hr><small>Command: ' + (result.command || 'N/A') + '</small></div>';
                    updateProgress(100, '✅ Campagnes succesvol aangemaakt!');
                } else {
                    container.innerHTML = '<div class="alert alert-danger"><h6>❌ Error:</h6><pre>' + (result.error || result.output) + '</pre><hr><small>Command: ' + (result.command || 'N/A') + '</small></div>';
                    updateProgress(100, '❌ Fout bij aanmaken campagnes');
                }
                container.style.display = 'block';
                
                // Hide progress bar after 2 seconds
                setTimeout(() => {
                    hideProgressBar();
                    enableCreateButton();
                }, 2000);
                
            } catch (error) {
                updateProgress(100, '❌ Netwerk fout');
                alert('Error: ' + error.message);
                hideProgressBar();
                enableCreateButton();
            }
        });

        function parseLabelsFromOutput(output) {
            const lines = output.split('\\n');
            const labels = [];
            
            for (const line of lines) {
                // Match both formats: 'label': impressions and "label": impressions
                const match = line.match(/['"]([^'"]+)['"]:\\s*(\\d+)\\s*impressions/);
                if (match) {
                    labels.push({
                        name: match[1],
                        impressions: parseInt(match[2])
                    });
                }
            }
            
            console.log('Parsed labels:', labels); // Debug log
            return labels;
        }

        // Seller Clicks Timeseries
        async function fetchSellerClicksTimeseries() {
            const customerId = document.getElementById('sellerClicksCustomerId').value.trim();
            const campaignName = document.getElementById('sellerClicksCampaignName').value.trim();
            const daysInput = document.getElementById('sellerClicksDays').value;
            const exportCsv = document.getElementById('sellerClicksExportCsv').checked;

            if (!customerId) {
                alert('Vul een Customer ID in.');
                return;
            }
            if (!campaignName) {
                alert('Vul een (deel van de) campagnenaam in.');
                return;
            }

            const days = daysInput === '' || daysInput === null ? 90 : parseInt(daysInput, 10);
            if (isNaN(days) || days <= 0) {
                alert('Vul een geldig aantal dagen in (bijv. 90).');
                return;
            }

            const resultsContainer = document.getElementById('sellerClicksResults');
            resultsContainer.innerHTML = `
                <div class="text-center">
                    <div class="spinner-border text-primary" role="status"></div><br>
                    <small>Seller klik-analyse wordt uitgevoerd...</small>
                </div>
            `;

            try {
                const response = await fetch('/api/seller-clicks-timeseries', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        customer_id: customerId,
                        campaign_name: campaignName,
                        days: days,
                        export_csv: exportCsv
                    })
                });

                const result = await response.json();

                if (result.success) {
                    const output = result.output || '';
                    const escapedOutput = output
                        .replace(/&/g, '&amp;')
                        .replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;');

                    resultsContainer.innerHTML = `
                        <pre class="small" style="white-space: pre-wrap; max-height: 400px; overflow-y: auto;">${escapedOutput}</pre>
                        <small class="text-muted d-block mt-2">Command: ${result.command || ''}</small>
                    `;
                } else {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-danger">
                            <h6>❌ Seller Klik-analyse Failed</h6>
                            <pre class="small" style="white-space: pre-wrap;">${(result.error || result.output || 'Onbekende fout').toString()}</pre>
                            <small class="text-muted d-block mt-2">Command: ${result.command || ''}</small>
                        </div>
                    `;
                }
            } catch (e) {
                resultsContainer.innerHTML = `
                    <div class="alert alert-danger">
                        <h6>❌ Seller Klik-analyse Exception</h6>
                        <pre class="small" style="white-space: pre-wrap;">${e}</pre>
                    </div>
                `;
            }
        }

        function updateLabelSelection() {
            const container = document.getElementById('labelSelection');
            
            if (discoveredLabels.length === 0) {
                container.innerHTML = '<small class="text-muted">Eerst labels ontdekken om ze hier te kunnen selecteren</small>';
                return;
            }
            
            let html = '<div class="mb-2"><small class="text-muted">Selecteer de labels waarvoor je campagnes wilt aanmaken:</small></div>';
            
            discoveredLabels.forEach((label, index) => {
                const cleanLabelName = label.name.trim();
                html += `<div class="label-checkbox">
                    <input type="checkbox" id="label_${index}" value="${cleanLabelName}" checked>
                    <label for="label_${index}">${cleanLabelName} (${label.impressions.toLocaleString()} impressies)</label>
                </div>`;
            });
            
            html += '<div class="mt-2"><button type="button" class="btn btn-sm btn-outline-primary" onclick="selectAll()">Alles selecteren</button> ';
            html += '<button type="button" class="btn btn-sm btn-outline-secondary" onclick="deselectAll()">Alles deselecteren</button></div>';
            html += '<div class="mt-2"><small class="text-info">💡 Tip: Selecteer alleen de labels waarvoor je campagnes wilt aanmaken</small></div>';
            
            container.innerHTML = html;
        }

        function getSelectedLabels() {
            const checkboxes = document.querySelectorAll('#labelSelection input[type="checkbox"]:checked');
            return Array.from(checkboxes).map(cb => cb.value.trim());
        }

        function selectAll() {
            document.querySelectorAll('#labelSelection input[type="checkbox"]').forEach(cb => cb.checked = true);
        }

        function deselectAll() {
            document.querySelectorAll('#labelSelection input[type="checkbox"]').forEach(cb => cb.checked = false);
        }

        // Country selection functions
        function selectAllCountries() {
            document.querySelectorAll('input[id^="country"]').forEach(cb => cb.checked = true);
        }

        function deselectAllCountries() {
            document.querySelectorAll('input[id^="country"]').forEach(cb => cb.checked = false);
        }

        function getSelectedCountries() {
            const checkboxes = document.querySelectorAll('input[id^="country"]:checked');
            return Array.from(checkboxes).map(cb => cb.value);
        }

        // Language selection functions
        function selectAllLanguages() {
            document.querySelectorAll('input[id^="lang"]').forEach(cb => cb.checked = true);
        }

        function deselectAllLanguages() {
            document.querySelectorAll('input[id^="lang"]').forEach(cb => cb.checked = false);
        }

        function getSelectedLanguages() {
            const checkboxes = document.querySelectorAll('input[id^="lang"]:checked');
            return Array.from(checkboxes).map(cb => cb.value);
        }
        
        function getSelectedPmaxCountries() {
            const checkboxes = document.querySelectorAll('input[id^="pmaxCountry"]:checked');
            return Array.from(checkboxes).map(cb => cb.value);
        }
        
        function getSelectedPmaxLanguages() {
            const checkboxes = document.querySelectorAll('input[id^="pmaxLang"]:checked');
            return Array.from(checkboxes).map(cb => cb.value);
        }
        
        function selectAllPmaxCountries() {
            document.querySelectorAll('input[id^="pmaxCountry"]').forEach(cb => cb.checked = true);
        }
        
        function deselectAllPmaxCountries() {
            document.querySelectorAll('input[id^="pmaxCountry"]').forEach(cb => cb.checked = false);
        }
        
        function selectAllPmaxLanguages() {
            document.querySelectorAll('input[id^="pmaxLang"]').forEach(cb => cb.checked = true);
        }
        
        function deselectAllPmaxLanguages() {
            document.querySelectorAll('input[id^="pmaxLang"]').forEach(cb => cb.checked = false);
        }

        // Feed label handling
        document.getElementById('feedLabel').addEventListener('change', function() {
            const customDiv = document.getElementById('customFeedLabelDiv');
            if (this.value === 'custom') {
                customDiv.style.display = 'block';
                document.getElementById('customFeedLabel').focus();
            } else {
                customDiv.style.display = 'none';
            }
        });

        function getFeedLabel() {
            const select = document.getElementById('feedLabel');
            if (select.value === 'custom') {
                return document.getElementById('customFeedLabel').value.trim();
            }
            return select.value;
        }
        
        function getPmaxFeedLabel() {
            const select = document.getElementById('pmaxFeedLabel');
            if (select.value === 'custom') {
                return document.getElementById('pmaxCustomFeedLabel').value.trim();
            }
            return select.value;
        }

        // PMax Campaign Functions
        async function previewPmaxCampaigns() {
            const customerId = document.getElementById('pmaxCustomerId').value.trim();
            if (!customerId) {
                alert('Vul een Customer ID in.');
                return;
            }
            
            const pmaxType = document.getElementById('pmaxTypeSelect').value;
            const merchantId = document.getElementById('pmaxMerchantId').value.trim();
            
            if (pmaxType === 'feed-only' && !merchantId) {
                alert('Vul een Merchant Center ID in. Dit is vereist voor Feed-Only PMax campagnes.');
                return;
            }
            
            const resultsContainer = document.getElementById('pmaxResults');
            resultsContainer.innerHTML = '<div class="text-center"><div class="spinner-border text-info" role="status"></div><br><small>Preview wordt gegenereerd...</small></div>';
            
            try {
                const response = await fetch('/api/preview-campaigns', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        customer_id: customerId,
                        campaign_type: 'pmax-all-labels',
                        label_index: parseInt(document.getElementById('pmaxLabelIndex').value),
                        merchant_id: merchantId,
                        pmax_type: pmaxType,
                        prefix: document.getElementById('pmaxPrefix').value || 'PMax ALL',
                        daily_budget: parseFloat(document.getElementById('pmaxDailyBudget').value),
                        roas_factor: parseFloat(document.getElementById('pmaxRoasFactor').value) || 0,
                        start_enabled: document.getElementById('pmaxStartEnabled').checked,
                        target_languages: getSelectedPmaxLanguages().join(','),
                        target_countries: getSelectedPmaxCountries().join(','),
                        feed_label: getPmaxFeedLabel()
                    })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-success">
                            <h6>✅ PMax Preview Completed</h6>
                            <pre style="max-height: 300px; overflow-y: auto;">${result.output}</pre>
                            <hr>
                            <small>Command: ${result.command}</small>
                        </div>
                    `;
                } else {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-danger">
                            <h6>❌ PMax Preview Failed</h6>
                            <pre>${result.error || result.output}</pre>
                            <hr>
                            <small>Command: ${result.command}</small>
                        </div>
                    `;
                }
            } catch (error) {
                resultsContainer.innerHTML = `
                    <div class="alert alert-danger">
                        <h6>❌ Network Error</h6>
                        <pre>${error.message}</pre>
                    </div>
                `;
            }
        }
        
        async function createPmaxCampaigns() {
            const customerId = document.getElementById('pmaxCustomerId').value.trim();
            if (!customerId) {
                alert('Vul een Customer ID in.');
                return;
            }
            
            const pmaxType = document.getElementById('pmaxTypeSelect').value;
            const merchantId = document.getElementById('pmaxMerchantId').value.trim();
            
            if (pmaxType === 'feed-only' && !merchantId) {
                alert('Vul een Merchant Center ID in. Dit is vereist voor Feed-Only PMax campagnes.');
                return;
            }
            
            if (!confirm('⚠️ Weet je zeker dat je PMax campagnes wilt aanmaken? Dit kan niet ongedaan worden gemaakt.')) {
                return;
            }
            
            const resultsContainer = document.getElementById('pmaxResults');
            resultsContainer.innerHTML = '<div class="text-center"><div class="spinner-border text-info" role="status"></div><br><small>PMax campagnes worden aangemaakt...</small></div>';
            
            try {
                const response = await fetch('/api/create-campaigns', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        customer_id: customerId,
                        campaign_type: 'pmax-all-labels',
                        label_index: parseInt(document.getElementById('pmaxLabelIndex').value),
                        merchant_id: merchantId,
                        pmax_type: pmaxType,
                        prefix: document.getElementById('pmaxPrefix').value || 'PMax ALL',
                        daily_budget: parseFloat(document.getElementById('pmaxDailyBudget').value),
                        roas_factor: parseFloat(document.getElementById('pmaxRoasFactor').value) || 0,
                        start_enabled: document.getElementById('pmaxStartEnabled').checked,
                        target_languages: getSelectedPmaxLanguages().join(','),
                        target_countries: getSelectedPmaxCountries().join(','),
                        feed_label: getPmaxFeedLabel()
                    })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-success">
                            <h6>✅ PMax Campagnes Aangemaakt</h6>
                            <pre style="max-height: 300px; overflow-y: auto;">${result.output}</pre>
                            <hr>
                            <small>Command: ${result.command}</small>
                        </div>
                    `;
                } else {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-danger">
                            <h6>❌ PMax Campaign Creation Failed</h6>
                            <pre>${result.error || result.output}</pre>
                            <hr>
                            <small>Command: ${result.command}</small>
                        </div>
                    `;
                }
            } catch (error) {
                resultsContainer.innerHTML = `
                    <div class="alert alert-danger">
                        <h6>❌ Network Error</h6>
                        <pre>${error.message}</pre>
                    </div>
                `;
            }
        }

        // Progress Bar Functions
        function showProgressBar() {
            document.getElementById('progressContainer').style.display = 'block';
            updateProgress(0, 'Initializing...');
        }

        function hideProgressBar() {
            document.getElementById('progressContainer').style.display = 'none';
        }

        function updateProgress(percentage, text) {
            const progressBar = document.getElementById('progressBar');
            const progressText = document.getElementById('progressText');
            const progressDetails = document.getElementById('progressDetails');
            
            progressBar.style.width = percentage + '%';
            progressBar.setAttribute('aria-valuenow', percentage);
            progressText.textContent = text;
            progressDetails.textContent = `${percentage}% voltooid`;
            
            // Change color based on progress
            if (percentage === 100) {
                progressBar.className = 'progress-bar progress-bar-striped bg-success';
            } else if (percentage >= 50) {
                progressBar.className = 'progress-bar progress-bar-striped progress-bar-animated bg-info';
            } else {
                progressBar.className = 'progress-bar progress-bar-striped progress-bar-animated bg-primary';
            }
        }

        function disableCreateButton() {
            const button = document.getElementById('createButton');
            button.disabled = true;
            button.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Bezig...';
        }

        function enableCreateButton() {
            const button = document.getElementById('createButton');
            button.disabled = false;
            button.innerHTML = 'Create Selected Campaigns';
        }

        function displayLabels(labels) {
            const container = document.getElementById('labelSelection');
            if (!container) {
                console.error('Label selection container not found');
                return;
            }
            
            if (!labels || labels.length === 0) {
                container.innerHTML = '<small class="text-muted">Geen labels gevonden</small>';
                return;
            }
            
            let html = '<div class="mb-2"><strong>Gevonden labels:</strong></div>';
            html += '<div class="row">';
            
            labels.forEach((label, index) => {
                const colClass = labels.length > 6 ? 'col-md-4' : 'col-md-6';
                html += `
                    <div class="${colClass}">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" id="label${index}" value="${label}" checked>
                            <label class="form-check-label" for="label${index}">${label}</label>
                        </div>
                    </div>
                `;
            });
            
            html += '</div>';
            html += '<div class="mt-2">';
            html += '<button type="button" class="btn btn-sm btn-outline-primary" onclick="selectAll()">Alles selecteren</button>';
            html += '<button type="button" class="btn btn-sm btn-outline-secondary" onclick="deselectAll()">Alles deselecteren</button></div>';
            html += '<div class="mt-2"><small class="text-info">💡 Tip: Selecteer alleen de labels waarvoor je campagnes wilt aanmaken</small></div>';
            
            container.innerHTML = html;
        }

        async function discoverLabels() {
            const customerId = document.getElementById('customerId').value.trim();
            const labelIndex = parseInt(document.getElementById('labelIndex').value);
            const merchantId = document.getElementById('merchantId').value.trim();
            
            if (!customerId) {
                alert('Vul een Customer ID in.');
                return;
            }
            
            console.log('Discovering labels for customer:', customerId, 'label index:', labelIndex); // Debug log
            
            const formData = {
                customer_id: customerId,
                label_index: labelIndex
            };
            
            if (merchantId) {
                formData.merchant_id = merchantId;
            }

            try {
                const response = await fetch('/api/discover-labels', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(formData)
                });
                
                const result = await response.json();
                
                const container = document.getElementById('discoverResults');
                if (result.success) {
                    container.innerHTML = '<div class="alert alert-success"><h6>✅ Labels gevonden:</h6><pre>' + result.output + '</pre><hr><small>Command: ' + (result.command || 'N/A') + '</small></div>';
                    
                    // Parse labels from output and display them in the campaign creation section
                    const output = result.output;
                    const labels = [];
                    
                    // Extract labels from the output (format: 'label': impressions)
                    const labelMatches = output.match(/'([^']+)': \\d+ impressions/g);
                    if (labelMatches) {
                        labelMatches.forEach(match => {
                            const label = match.match(/'([^']+)'/)[1];
                            labels.push(label);
                        });
                    }
                    
                    // Display labels in the campaign creation section
                    displayLabels(labels);
                    
                    // Auto-fill Customer ID and Merchant ID from discover form
                    const createCustomerId = document.getElementById('createCustomerId');
                    const merchantIdCreate = document.getElementById('merchantIdCreate');
                    
                    if (createCustomerId && customerId) {
                        createCustomerId.value = customerId;
                    }
                    
                    if (merchantIdCreate && merchantId) {
                        merchantIdCreate.value = merchantId;
                    }
                    
                } else {
                    container.innerHTML = '<div class="alert alert-danger"><h6>❌ Error:</h6><pre>' + (result.error || result.output) + '</pre><hr><small>Command: ' + (result.command || 'N/A') + '</small></div>';
                }
                container.style.display = 'block';
                
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }

        async function previewCampaigns() {
            // Campaign preview now only supports Standard Shopping (product-type)
            const campaignType = 'product-type';
            
            const customerId = document.getElementById('createCustomerId').value.trim();
            if (!customerId) {
                alert('Vul een Customer ID in.');
                return;
            }
            
            const merchantId = document.getElementById('merchantIdCreate').value.trim();
            if (!merchantId) {
                alert('Vul een Merchant Center ID in. Dit is vereist voor Standard Shopping campagnes.');
                return;
            }
            
            console.log('Campaign type for preview:', campaignType); // Debug log
            console.log('Customer ID for preview:', customerId); // Debug log
            
            // Show progress bar
            showProgressBar();
            
            const formData = {
                customer_id: customerId,
                campaign_type: campaignType,
                label_index: parseInt(document.getElementById('createLabelIndex').value),
                merchant_id: merchantId,
                prefix: document.getElementById('campaignPrefix').value,
                daily_budget: parseFloat(document.getElementById('dailyBudget').value),
                roas_factor: parseFloat(document.getElementById('roasFactor').value) || 0,
                start_enabled: document.getElementById('startEnabled').checked,
                target_languages: getSelectedLanguages().join(','),
                target_countries: getSelectedCountries().join(','),
                feed_label: getFeedLabel()
            };

            try {
                updateProgress(25, 'Preview wordt gegenereerd...');
                
                const response = await fetch('/api/preview-campaigns', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(formData)
                });
                
                updateProgress(75, 'Preview wordt verwerkt...');
                
                const result = await response.json();
                
                updateProgress(100, '✅ Preview voltooid!');
                
                const container = document.getElementById('previewResults');
                if (result.success) {
                    container.innerHTML = '<div class="alert alert-info"><h6>📋 Preview van campagnes die aangemaakt gaan worden:</h6><pre>' + result.output + '</pre><hr><small>Command: ' + (result.command || 'N/A') + '</small></div>';
                } else {
                    container.innerHTML = '<div class="alert alert-danger"><h6>❌ Error:</h6><pre>' + (result.error || result.output) + '</pre><hr><small>Command: ' + (result.command || 'N/A') + '</small></div>';
                }
                container.style.display = 'block';
                
                // Hide progress bar after 1 second
                setTimeout(() => {
                    hideProgressBar();
                }, 1000);
                
            } catch (error) {
                updateProgress(100, '❌ Netwerk fout');
                alert('Error: ' + error.message);
                hideProgressBar();
            }
        }

        // Weekly Monitor Functions
        async function runWeeklyMonitor() {
            const customerId = document.getElementById('monitorCustomerId').value.trim();
            const prefix = document.getElementById('monitorPrefix').value.trim();
            const labelIndex = parseInt(document.getElementById('monitorLabelIndex').value);
            const minImpressions = parseInt(document.getElementById('minImpressions').value);
            const minConversions = parseInt(document.getElementById('minConversions').value);
            const autoPauseEmpty = document.getElementById('autoPauseEmpty').checked;
            const detailedReport = document.getElementById('detailedReport').checked;
            const exportCsv = document.getElementById('exportCsv').checked;
            
            // Get performance metrics options
            const includeROAS = document.getElementById('includeROAS').checked;
            const includeCTR = document.getElementById('includeCTR').checked;
            const includeBudget = document.getElementById('includeBudget').checked;
            const includeVolume = document.getElementById('includeVolume').checked;
            const includeLabels = document.getElementById('includeLabels').checked;
            const includeTrends = document.getElementById('includeTrends').checked;
            
            if (!customerId) {
                alert('Vul een Customer ID in.');
                return;
            }
            
            const resultsContainer = document.getElementById('monitorResults');
            resultsContainer.innerHTML = '<div class="text-center"><div class="spinner-border text-warning" role="status"></div><br><small>Weekly monitor wordt uitgevoerd...</small></div>';
            
            try {
                const response = await fetch('/api/weekly-monitor', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        customer_id: customerId,
                        prefix: prefix,
                        label_index: labelIndex,
                        min_impressions: minImpressions,
                        min_conversions: minConversions,
                        auto_pause_empty: autoPauseEmpty,
                        apply_changes: false,
                        detailed_report: detailedReport,
                        export_csv: exportCsv,
                        include_roas: includeROAS,
                        include_ctr: includeCTR,
                        include_budget: includeBudget,
                        include_volume: includeVolume,
                        include_labels: includeLabels,
                        include_trends: includeTrends
                    })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-success">
                            <h6>✅ Weekly Monitor Completed</h6>
                            <pre style="max-height: 300px; overflow-y: auto;">${result.output}</pre>
                            <hr>
                            <small>Command: ${result.command}</small>
                        </div>
                    `;
                    
                    // Show action buttons
                    document.getElementById('applyChangesBtn').style.display = 'inline-block';
                    document.getElementById('viewDetailsBtn').style.display = 'inline-block';
                    
                } else {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-danger">
                            <h6>❌ Weekly Monitor Failed</h6>
                            <pre>${result.error || result.output}</pre>
                            <hr>
                            <small>Command: ${result.command}</small>
                        </div>
                    `;
                }
                
            } catch (error) {
                resultsContainer.innerHTML = `
                    <div class="alert alert-danger">
                        <h6>❌ Network Error</h6>
                        <pre>${error.message}</pre>
                    </div>
                `;
            }
        }

        async function applyWeeklyChanges() {
            const customerId = document.getElementById('monitorCustomerId').value.trim();
            const prefix = document.getElementById('monitorPrefix').value.trim();
            const labelIndex = parseInt(document.getElementById('monitorLabelIndex').value);
            const minImpressions = parseInt(document.getElementById('minImpressions').value);
            const minConversions = parseInt(document.getElementById('minConversions').value);
            const autoPauseEmpty = document.getElementById('autoPauseEmpty').checked;
            const detailedReport = document.getElementById('detailedReport').checked;
            const exportCsv = document.getElementById('exportCsv').checked;
            
            if (!confirm('⚠️ Weet je zeker dat je de wijzigingen wilt doorvoeren? Dit kan niet ongedaan worden gemaakt.')) {
                return;
            }
            
            const resultsContainer = document.getElementById('monitorResults');
            resultsContainer.innerHTML = '<div class="text-center"><div class="spinner-border text-success" role="status"></div><br><small>Wijzigingen worden doorgevoerd...</small></div>';
            
            try {
                const response = await fetch('/api/weekly-monitor', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        customer_id: customerId,
                        prefix: prefix,
                        label_index: labelIndex,
                        min_impressions: minImpressions,
                        min_conversions: minConversions,
                        auto_pause_empty: autoPauseEmpty,
                        apply_changes: true,
                        detailed_report: detailedReport,
                        export_csv: exportCsv
                    })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-success">
                            <h6>✅ Changes Applied Successfully</h6>
                            <pre style="max-height: 300px; overflow-y: auto;">${result.output}</pre>
                            <hr>
                            <small>Command: ${result.command}</small>
                        </div>
                    `;
                    
                    // Hide action buttons after successful application
                    document.getElementById('applyChangesBtn').style.display = 'none';
                    document.getElementById('viewDetailsBtn').style.display = 'none';
                    
                } else {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-danger">
                            <h6>❌ Failed to Apply Changes</h6>
                            <pre>${result.error || result.output}</pre>
                            <hr>
                            <small>Command: ${result.command}</small>
                        </div>
                    `;
                }
                
            } catch (error) {
                resultsContainer.innerHTML = `
                    <div class="alert alert-danger">
                        <h6>❌ Network Error</h6>
                        <pre>${error.message}</pre>
                    </div>
                `;
            }
        }
        
        // PMax ROAS Adjustment Functions
        async function adjustPmaxRoas() {
            const customerId = document.getElementById('adjustPmaxRoasCustomerId').value.trim();
            const prefix = document.getElementById('adjustPmaxRoasPrefix').value.trim();
            const reset = document.getElementById('adjustPmaxRoasReset').checked;
            const percentageInput = document.getElementById('adjustPmaxRoasPercentage').value;
            const percentage = percentageInput === '' || percentageInput === null ? 0 : parseFloat(percentageInput);
            const apply = document.getElementById('adjustPmaxRoasApply').checked;
            
            if (!customerId) {
                alert('Vul een Customer ID in.');
                return;
            }
            
            if (!reset && (isNaN(percentage) || percentage === 0)) {
                alert('Vul een percentage in (niet 0) of vink "Eerst resetten" aan (of beide).');
                return;
            }
            
            const resultsContainer = document.getElementById('adjustPmaxRoasResults');
            const actionText = reset ? (percentage !== 0 ? 'gereset en aangepast' : 'gereset') : 'aangepast';
            resultsContainer.innerHTML = `<div class="text-center"><div class="spinner-border text-success" role="status"></div><br><small>PMax ROAS wordt ${actionText}...</small></div>`;
            
            try {
                const response = await fetch('/api/adjust-pmax-roas', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        customer_id: customerId,
                        prefix: prefix || null,
                        percentage: percentage,
                        reset: reset,
                        apply: apply
                    })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-success">
                            <h6>✅ PMax ROAS Adjustment ${apply ? 'Completed' : 'Preview'}</h6>
                            <pre style="max-height: 400px; overflow-y: auto; white-space: pre-wrap;">${result.output}</pre>
                            <hr>
                            <small>Command: ${result.command}</small>
                        </div>
                    `;
                } else {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-danger">
                            <h6>❌ PMax ROAS Adjustment Failed</h6>
                            <pre>${result.error || result.output}</pre>
                            <hr>
                            <small>Command: ${result.command || 'N/A'}</small>
                        </div>
                    `;
                }
            } catch (error) {
                resultsContainer.innerHTML = `
                    <div class="alert alert-danger">
                        <h6>❌ Network Error</h6>
                        <pre>${error.message}</pre>
                    </div>
                `;
            }
        }

        function viewWeeklyChanges() {
            // This function can be expanded to show more detailed information
            alert('[DETAILS] Detailed monitoring information will be displayed here in future versions.');
        }

        // Portfolio ROAS Adjustment Functions
        async function adjustPortfolioRoas() {
            const customerId = document.getElementById('adjustRoasCustomerId').value.trim();
            const reset = document.getElementById('adjustRoasReset').checked;
            const percentageInput = document.getElementById('adjustRoasPercentage').value;
            const percentage = percentageInput === '' || percentageInput === null ? 0 : parseFloat(percentageInput);
            const apply = document.getElementById('adjustRoasApply').checked;
            
            if (!customerId) {
                alert('Vul een Customer ID in.');
                return;
            }
            
            if (!reset && (isNaN(percentage) || percentage === 0)) {
                alert('Vul een percentage in (niet 0) of vink "Eerst resetten naar standaard waarde" aan (of beide).');
                return;
            }
            
            const pctText = !isNaN(percentage) && percentage !== 0 ? ` met ${percentage > 0 ? '+' : ''}${percentage}%` : '';
            const confirmMessage = reset 
                ? `⚠️ Eerst resetten naar standaard (seller marge)${pctText}. Weet je zeker? Dit kan niet ongedaan worden gemaakt.`
                : `⚠️ Weet je zeker dat je alle tROAS strategies wilt aanpassen met ${percentage > 0 ? '+' : ''}${percentage}%? Dit kan niet ongedaan worden gemaakt.`;
            
            if (apply && !confirm(confirmMessage)) {
                return;
            }
            
            const resultsContainer = document.getElementById('adjustRoasResults');
            const actionText = reset ? (percentage !== 0 ? 'gereset en aangepast' : 'gereset') : 'aangepast';
            resultsContainer.innerHTML = `<div class="text-center"><div class="spinner-border text-info" role="status"></div><br><small>Portfolio ROAS wordt ${actionText}...</small></div>`;
            
            try {
                const response = await fetch('/api/adjust-portfolio-roas', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        customer_id: customerId,
                        percentage: percentage,
                        reset: reset,
                        apply: apply
                    })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-success">
                            <h6>✅ Portfolio ROAS Adjustment ${apply ? 'Completed' : 'Preview'}</h6>
                            <pre style="max-height: 400px; overflow-y: auto; white-space: pre-wrap;">${result.output}</pre>
                            <hr>
                            <small>Command: ${result.command}</small>
                        </div>
                    `;
                } else {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-danger">
                            <h6>❌ Portfolio ROAS Adjustment Failed</h6>
                            <pre>${result.error || result.output}</pre>
                            <hr>
                            <small>Command: ${result.command || 'N/A'}</small>
                        </div>
                    `;
                }
            } catch (error) {
                resultsContainer.innerHTML = `
                    <div class="alert alert-danger">
                        <h6>❌ Network Error</h6>
                        <pre>${error.message}</pre>
                    </div>
                `;
            }
        }

        // Delete Inactive Campaigns
        async function deleteInactiveCampaigns() {
            const customerId = document.getElementById('deleteInactiveCustomerId').value.trim();
            const daysInput = document.getElementById('deleteInactiveDays').value;
            const days = daysInput === '' || daysInput === null ? 60 : parseInt(daysInput, 10);
            const apply = document.getElementById('deleteInactiveApply').checked;

            if (!customerId) {
                alert('Vul een Customer ID in.');
                return;
            }

            if (isNaN(days) || days <= 0) {
                alert('Vul een geldig aantal dagen in (bijv. 60).');
                return;
            }

            if (apply) {
                const confirmMsg = `⚠️ Weet je zeker dat je campagnes zonder impressies in de laatste ${days} dagen wilt VERWIJDEREN (Shopping & PMax)?` +
                    ` Biedstrategieën worden NIET automatisch verwijderd. Dit kan niet ongedaan worden gemaakt.`;
                if (!confirm(confirmMsg)) {
                    return;
                }
            }

            const resultsContainer = document.getElementById('deleteInactiveResults');
            resultsContainer.innerHTML = `<div class="text-center"><div class="spinner-border text-danger" role="status"></div><br><small>Zoeken en verwijderen van inactieve campagnes...</small></div>`;

            try {
                const response = await fetch('/api/delete-inactive-campaigns', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        customer_id: customerId,
                        days_without_impressions: days,
                        apply: apply
                    })
                });

                const result = await response.json();

                if (result.success) {
                    const output = result.output || '';
                    const escapedOutput = output.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                    resultsContainer.innerHTML = `
                        <pre class="small" style="white-space: pre-wrap; max-height: 400px; overflow-y: auto;">${escapedOutput}</pre>
                        <small class="text-muted d-block mt-2">Command: ${result.command || ''}</small>
                    `;
                } else {
                    resultsContainer.innerHTML = `
                        <div class="alert alert-danger">
                            <h6>❌ Delete Inactive Campaigns Failed</h6>
                            <pre class="small" style="white-space: pre-wrap;">${(result.error || result.output || 'Onbekende fout').toString()}</pre>
                        </div>
                    `;
                }
            } catch (e) {
                resultsContainer.innerHTML = `
                    <div class="alert alert-danger">
                        <h6>❌ Delete Inactive Campaigns Exception</h6>
                        <pre class="small" style="white-space: pre-wrap;">${e}</pre>
                    </div>
                `;
            }
        }
    </script>
</body>
</html>
"""


# Separate, minimal template for Seller Klik-analyse only
SELLER_CLICKS_TEMPLATE = """
<!DOCTYPE html>
<html lang="nl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Seller Klik-analyse - SDeal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f5f5f5; }
        .tool-card { border: none; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.1); margin-top: 30px; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container">
            <a class="navbar-brand" href="/">SDeal Google Ads Tools</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#mainNavbar" aria-controls="mainNavbar" aria-expanded="false" aria-label="Toggle navigation">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="mainNavbar">
                <ul class="navbar-nav ms-auto">
                    <li class="nav-item">
                        <a class="nav-link" href="/">← Terug naar hoofdtools</a>
                    </li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container my-4" id="top">
        <div class="alert alert-info">
            <strong>Seller Klik-analyse</strong> – tijdreeks per dag voor een campagnenaam, laatste N dagen.
        </div>

        <!-- Global account selector (hergebruikt /api/accounts) -->
        <div class="card mb-4">
            <div class="card-body">
                <div class="row g-3 align-items-end">
                    <div class="col-md-6">
                        <label for="globalAccountSelectSeller" class="form-label">Account selectie</label>
                        <select id="globalAccountSelectSeller" class="form-select">
                            <option value="">-- Kies account (Ads + Merchant) --</option>
                        </select>
                        <div class="form-text">
                            Kies een account om het Customer ID automatisch in te vullen.
                        </div>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label">Customer ID (doelaccount)</label>
                        <input type="text" class="form-control" id="sellerClicksCustomerId" placeholder="123-456-7890">
                    </div>
                </div>
            </div>
        </div>

        <!-- Seller Clicks Timeseries (last N days) -->
        <div class="row" id="section-seller-clicks">
            <div class="col-12">
                <div class="card tool-card">
                    <div class="card-header bg-info text-white">
                        <h5 class="mb-0">📈 Seller Klik-analyse (per dag, laatste N dagen)</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6>[ANALYSE] Kliks per dag voor een campagnenaam</h6>
                                <p class="text-muted">
                                    Haal een tijdreeks op met impressies, kliks, conversies, waarde en kosten per dag voor alle campagnes
                                    waarvan de naam een bepaalde tekst bevat (bijv. <code>EchtVeelVoorWeinig</code>).<br>
                                    Later kan deze filter eenvoudig worden omgezet naar een seller ID.
                                </p>
                                
                                <form id="sellerClicksForm" onsubmit="event.preventDefault(); fetchSellerClicksTimeseries();">
                                    <div class="mb-3">
                                        <label class="form-label">Customer ID *</label>
                                        <input type="text" class="form-control" id="sellerClicksCustomerId" required placeholder="123-456-7890">
                                    </div>

                                    <div class="mb-3">
                                        <label class="form-label">Campagnenaam (substring) *</label>
                                        <input type="text" class="form-control" id="sellerClicksCampaignName" required placeholder="EchtVeelVoorWeinig">
                                        <small class="form-text text-muted">
                                            We zoeken naar campagnes waarvan de naam deze tekst bevat (hoofdlettergevoelig zoals in Google Ads).
                                        </small>
                                    </div>

                                    <div class="mb-3">
                                        <label class="form-label">Dagen terug</label>
                                        <input type="number" class="form-control" id="sellerClicksDays" value="90" min="1" max="365">
                                    </div>

                                    <div class="mb-3">
                                        <div class="form-check">
                                            <input class="form-check-input" type="checkbox" id="sellerClicksExportCsv">
                                            <label class="form-check-label" for="sellerClicksExportCsv">
                                                Exporteer ook naar CSV (map <code>reports/</code> in dit project)
                                            </label>
                                        </div>
                                    </div>

                                    <button type="submit" class="btn btn-primary">
                                        [RUN] Seller Klik-analyse
                                    </button>
                                </form>
                            </div>

                            <div class="col-md-6">
                                <h6>[RESULTS] Seller Kliks per Dag</h6>
                                <div id="sellerClicksResults" class="border rounded p-3" style="background: #f8f9fa; min-height: 200px;">
                                    <small class="text-muted">
                                        Vul het formulier in en klik op "Seller Klik-analyse" om de tijdreeks per dag te zien.
                                    </small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
    async function loadAccountsConfigSeller() {
        try {
            const resp = await fetch('/api/accounts');
            const data = await resp.json();
            if (!data.success || !Array.isArray(data.accounts)) {
                console.warn('Kon accounts niet laden voor seller clicks:', data.error || data);
                return;
            }
            const select = document.getElementById('globalAccountSelectSeller');
            select.innerHTML = '<option value=\"\">-- Kies account (Ads + Merchant) --</option>';

            data.accounts.forEach(acc => {
                const opt = document.createElement('option');
                opt.value = acc.key;
                const firstCustomer = (acc.customer_ids && acc.customer_ids[0]) || '';
                opt.textContent = acc.label + (firstCustomer ? ' (' + firstCustomer + ')' : '');
                opt.dataset.customerId = firstCustomer;
                select.appendChild(opt);
            });

            select.addEventListener('change', () => {
                const opt = select.options[select.selectedIndex];
                const cid = opt && opt.dataset.customerId ? opt.dataset.customerId : '';
                if (cid) {
                    const el = document.getElementById('sellerClicksCustomerId');
                    if (el) el.value = cid;
                }
            });
        } catch (e) {
            console.warn('Error loading accounts config for seller clicks:', e);
        }
    }

    async function fetchSellerClicksTimeseries() {
        const customerId = document.getElementById('sellerClicksCustomerId').value.trim();
        const campaignName = document.getElementById('sellerClicksCampaignName').value.trim();
        const daysInput = document.getElementById('sellerClicksDays').value;
        const exportCsv = document.getElementById('sellerClicksExportCsv').checked;

        if (!customerId) {
            alert('Vul een Customer ID in.');
            return;
        }
        if (!campaignName) {
            alert('Vul een (deel van de) campagnenaam in.');
            return;
        }

        const days = daysInput === '' || daysInput === null ? 90 : parseInt(daysInput, 10);
        if (isNaN(days) || days <= 0) {
            alert('Vul een geldig aantal dagen in (bijv. 90).');
            return;
        }

        const resultsContainer = document.getElementById('sellerClicksResults');
        resultsContainer.innerHTML = `
            <div class="text-center">
                <div class="spinner-border text-primary" role="status"></div><br>
                <small>Seller klik-analyse wordt uitgevoerd...</small>
            </div>
        `;

        try {
            const response = await fetch('/api/seller-clicks-timeseries', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    customer_id: customerId,
                    campaign_name: campaignName,
                    days: days,
                    export_csv: exportCsv
                })
            });

            const result = await response.json();

            if (result.success) {
                const output = result.output || '';
                const escapedOutput = output
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;');

                resultsContainer.innerHTML = `
                    <pre class="small" style="white-space: pre-wrap; max-height: 400px; overflow-y: auto;">${escapedOutput}</pre>
                    <small class="text-muted d-block mt-2">Command: ${result.command || ''}</small>
                `;
            } else {
                resultsContainer.innerHTML = `
                    <div class="alert alert-danger">
                        <h6>❌ Seller Klik-analyse Failed</h6>
                        <pre class="small" style="white-space: pre-wrap;">${(result.error || result.output || 'Onbekende fout').toString()}</pre>
                        <small class="text-muted d-block mt-2">Command: ${result.command || ''}</small>
                    </div>
                `;
            }
        } catch (e) {
            resultsContainer.innerHTML = `
                <div class="alert alert-danger">
                    <h6>❌ Seller Klik-analyse Exception</h6>
                    <pre class="small" style="white-space: pre-wrap;">${e}</pre>
                </div>
            `;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        loadAccountsConfigSeller();
    });
    </script>
</body>
</html>
"""


# Separate, minimal template for Seller ROAS per seller (account-level overzicht)
SELLER_PERFORMANCE_TEMPLATE = """
<!DOCTYPE html>
<html lang="nl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Seller ROAS overzicht - SDeal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f5f5f5; }
        .tool-card { border: none; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.1); margin-top: 30px; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container">
            <a class="navbar-brand" href="/">SDeal Google Ads Tools</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#mainNavbar" aria-controls="mainNavbar" aria-expanded="false" aria-label="Toggle navigation">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="mainNavbar">
                <ul class="navbar-nav ms-auto">
                    <li class="nav-item">
                        <a class="nav-link" href="/">← Terug naar hoofdtools</a>
                    </li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container my-4" id="top">
        <div class="alert alert-info">
            <strong>Seller ROAS overzicht</strong> – per seller (custom_label_0) omzet, kosten en ROAS over de laatste N dagen.
        </div>

        <!-- Global account selector (hergebruikt /api/accounts) -->
        <div class="card mb-4">
            <div class="card-body">
                <div class="row g-3 align-items-end">
                    <div class="col-md-6">
                        <label for="globalAccountSelectSellerRoas" class="form-label">Account selectie</label>
                        <select id="globalAccountSelectSellerRoas" class="form-select">
                            <option value="">-- Kies account (Ads + Merchant) --</option>
                        </select>
                        <div class="form-text">
                            Kies een account om het Customer ID automatisch in te vullen.
                        </div>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label">Customer ID (doelaccount)</label>
                        <input type="text" class="form-control" id="sellerRoasCustomerId" placeholder="123-456-7890">
                    </div>
                </div>
            </div>
        </div>

        <!-- Seller ROAS sectie -->
        <div class="row" id="section-seller-roas">
            <div class="col-12">
                <div class="card tool-card">
                    <div class="card-header bg-success text-white">
                        <h5 class="mb-0">📊 Seller ROAS per seller (omzet, kosten, ROAS)</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6>[ANALYSE] Per-seller ROAS</h6>
                                <p class="text-muted">
                                    Toont per seller (gebaseerd op <code>custom_label_0</code> / product_custom_attribute0)
                                    de totale omzet, kosten en ROAS (omzet / kosten) over de laatste N dagen.
                                </p>
                                
                                <form id="sellerRoasForm" onsubmit="event.preventDefault(); fetchSellerRoasOverview();">
                                    <div class="mb-3">
                                        <label class="form-label">Customer ID *</label>
                                        <input type="text" class="form-control" id="sellerRoasCustomerId" required placeholder="123-456-7890">
                                    </div>

                                    <div class="mb-3">
                                        <label class="form-label">Dagen terug</label>
                                        <input type="number" class="form-control" id="sellerRoasDays" value="30" min="1" max="365">
                                    </div>

                                    <button type="submit" class="btn btn-success">
                                        [RUN] Seller ROAS overzicht
                                    </button>
                                </form>
                            </div>

                            <div class="col-md-6">
                                <h6>[RESULTS] Seller ROAS</h6>
                                <div id="sellerRoasResults" class="border rounded p-3" style="background: #f8f9fa; min-height: 200px;">
                                    <small class="text-muted">
                                        Vul het formulier in en klik op "Seller ROAS overzicht" om de lijst per seller te zien.
                                    </small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
    async function loadAccountsConfigSellerRoas() {
        try {
            const resp = await fetch('/api/accounts');
            const data = await resp.json();
            if (!data.success || !Array.isArray(data.accounts)) {
                console.warn('Kon accounts niet laden voor seller ROAS:', data.error || data);
                return;
            }
            const select = document.getElementById('globalAccountSelectSellerRoas');
            select.innerHTML = '<option value=\"\">-- Kies account (Ads + Merchant) --</option>';

            data.accounts.forEach(acc => {
                const opt = document.createElement('option');
                opt.value = acc.key;
                const firstCustomer = (acc.customer_ids && acc.customer_ids[0]) || '';
                opt.textContent = acc.label + (firstCustomer ? ' (' + firstCustomer + ')' : '');
                opt.dataset.customerId = firstCustomer;
                select.appendChild(opt);
            });

            select.addEventListener('change', () => {
                const opt = select.options[select.selectedIndex];
                const cid = opt && opt.dataset.customerId ? opt.dataset.customerId : '';
                if (cid) {
                    const el = document.getElementById('sellerRoasCustomerId');
                    if (el) el.value = cid;
                }
            });
        } catch (e) {
            console.warn('Error loading accounts config for seller ROAS:', e);
        }
    }

    async function fetchSellerRoasOverview() {
        const customerId = document.getElementById('sellerRoasCustomerId').value.trim();
        const daysInput = document.getElementById('sellerRoasDays').value;

        if (!customerId) {
            alert('Vul een Customer ID in.');
            return;
        }

        const days = daysInput === '' || daysInput === null ? 30 : parseInt(daysInput, 10);
        if (isNaN(days) || days <= 0) {
            alert('Vul een geldig aantal dagen in (bijv. 30).');
            return;
        }

        const resultsContainer = document.getElementById('sellerRoasResults');
        resultsContainer.innerHTML = `
            <div class="text-center">
                <div class="spinner-border text-success" role="status"></div><br>
                <small>Seller ROAS overzicht wordt opgehaald...</small>
            </div>
        `;

        try {
            const response = await fetch('/api/account-seller-roas', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    customer_id: customerId,
                    days: days
                })
            });

            const result = await response.json();

            if (result.success) {
                const output = result.output || '';
                const escapedOutput = output
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;');

                resultsContainer.innerHTML = `
                    <pre class="small" style="white-space: pre-wrap; max-height: 400px; overflow-y: auto;">${escapedOutput}</pre>
                    <small class="text-muted d-block mt-2">Command: ${result.command || ''}</small>
                `;
            } else {
                resultsContainer.innerHTML = `
                    <div class="alert alert-danger">
                        <h6>❌ Seller ROAS overzicht Failed</h6>
                        <pre class="small" style="white-space: pre-wrap;">${(result.error || result.output || 'Onbekende fout').toString()}</pre>
                        <small class="text-muted d-block mt-2">Command: ${result.command || ''}</small>
                    </div>
                `;
            }
        } catch (e) {
            resultsContainer.innerHTML = `
                <div class="alert alert-danger">
                    <h6>❌ Seller ROAS overzicht Exception</h6>
                    <pre class="small" style="white-space: pre-wrap;">${e}</pre>
                </div>
            `;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        loadAccountsConfigSellerRoas();
    });
    </script>
</body>
</html>
"""
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/seller-clicks')
def seller_clicks_page():
    """Separate, minimal page for Seller Klik-analyse (voor andere gebruikers)."""
    return render_template_string(SELLER_CLICKS_TEMPLATE)


@app.route('/seller-performance')
def seller_performance_page():
    """Separate, minimal page voor Seller ROAS per seller (account-niveau)."""
    return render_template_string(SELLER_PERFORMANCE_TEMPLATE)

@app.route('/api/discover-labels', methods=['POST'])
def discover_labels():
    try:
        data = request.json
        print(f"Received data: {data}")  # Debug log
        
        python_exe = get_python_executable()
        cmd = [
            python_exe, 'src/label_campaigns.py',
            '--customer', data.get('customer_id'),
            '--label-index', str(data.get('label_index', 0)),
            '--apply', 'false'
        ]
        
        if data.get('merchant_id'):
            cmd.extend(['--merchant-id', data.get('merchant_id')])
        
        if data.get('extended_search', False):
            cmd.append('--extended-search')
        
        print(f"Running command: {' '.join(cmd)}")  # Debug log
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)
        
        print(f"Return code: {result.returncode}")  # Debug log
        print(f"Stdout: {result.stdout[:200]}...")  # Debug log
        print(f"Stderr: {result.stderr[:200]}...")  # Debug log
        
        return jsonify({
            'success': result.returncode == 0,
            'output': result.stdout if result.returncode == 0 else result.stderr,
            'command': ' '.join(cmd)  # Return command for debugging
        })
    except Exception as e:
        print(f"Exception: {e}")  # Debug log
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/seller-clicks-timeseries', methods=['POST'])
def seller_clicks_timeseries():
    """Run the seller_clicks_timeseries CLI tool and return its output."""
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        campaign_name = data.get('campaign_name')
        days = int(data.get('days', 90) or 90)
        export_csv = bool(data.get('export_csv', False))

        if not customer_id:
            return jsonify({'success': False, 'error': 'Customer ID is required'})
        if not campaign_name:
            return jsonify({'success': False, 'error': 'Campaign name substring is required'})

        python_exe = get_python_executable()
        print(f"DEBUG: Detected Python executable: {python_exe}")
        print(f"DEBUG: sys.executable = {sys.executable}")
        
        cmd = [
            python_exe,
            'src/seller_clicks_timeseries.py',
            '--customer', customer_id,
            '--campaign-name', campaign_name,
            '--days', str(days)
        ]

        if export_csv:
            cmd.append('--export-csv')

        print(f"Running command (seller clicks): {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)

        print(f"Return code (seller clicks): {result.returncode}")
        print(f"Stdout (seller clicks): {result.stdout[:500]}...")
        print(f"Stderr (seller clicks): {result.stderr[:500]}...")

        return jsonify({
            'success': result.returncode == 0,
            'output': result.stdout if result.returncode == 0 else result.stderr,
            'command': ' '.join(cmd)
        })

    except Exception as e:
        print(f"Seller clicks exception: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/account-seller-roas', methods=['POST'])
def account_seller_roas():
    """Run the account_seller_roas CLI tool and return its output."""
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        days = int(data.get('days', 30) or 30)

        if not customer_id:
            return jsonify({'success': False, 'error': 'Customer ID is required'})

        python_exe = get_python_executable()
        cmd = [
            python_exe,
            'src/account_seller_roas.py',
            '--customer', customer_id,
            '--days', str(days),
        ]

        print(f"Running command (account seller roas): {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)

        print(f"Return code (account seller roas): {result.returncode}")
        print(f"Stdout (account seller roas): {result.stdout[:500]}...")
        print(f"Stderr (account seller roas): {result.stderr[:500]}...")

        return jsonify({
            'success': result.returncode == 0,
            'output': result.stdout if result.returncode == 0 else result.stderr,
            'command': ' '.join(cmd),
        })
    except Exception as e:
        print(f"Account seller ROAS exception: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    """Return configured accounts (Ads + Merchant) from config/accounts.json."""
    try:
        cfg_path = Path(__file__).parent / 'config' / 'accounts.json'
        if not cfg_path.exists():
            return jsonify({'success': False, 'error': 'accounts.json not found'})
        
        raw = cfg_path.read_text(encoding='utf-8')
        data = json.loads(raw)
        
        accounts = []
        for key, acc in data.items():
            accounts.append({
                'key': key,
                'label': acc.get('label', key),
                'country': acc.get('country'),
                'customer_ids': acc.get('google_ads_customer_ids', []),
                'merchant_id': acc.get('merchant_id')
            })
        
        return jsonify({'success': True, 'accounts': accounts})
    except Exception as e:
        print(f"Accounts config exception: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/delete-inactive-campaigns', methods=['POST'])
def delete_inactive_campaigns():
    """Delete inactive Shopping & PMax campaigns (0 impressions for N days). Strategies are only reported, not deleted."""
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        days = int(data.get('days_without_impressions', 60) or 60)
        apply = bool(data.get('apply', False))

        if not customer_id:
            return jsonify({'success': False, 'error': 'Customer ID is required'})

        python_exe = get_python_executable()
        cmd = [
            python_exe,
            'src/delete_inactive_campaigns.py',
            '--customer', customer_id,
            '--days', str(days)
        ]

        if apply:
            cmd.append('--apply')

        print(f"Running command: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)

        print(f"Return code (delete inactive): {result.returncode}")
        print(f"Stdout: {result.stdout}")
        print(f"Stderr: {result.stderr}")

        return jsonify({
            'success': result.returncode == 0,
            'output': result.stdout if result.returncode == 0 else result.stderr,
            'command': ' '.join(cmd)
        })

    except Exception as e:
        print(f"Delete inactive campaigns exception: {e}")
        return jsonify({'success': False, 'error': str(e)})




@app.route('/api/preview-campaigns', methods=['POST'])
def preview_campaigns():
    try:
        data = request.json
        campaign_type = data.get('campaign_type', 'standard')
        
        print(f"Preview request - campaign_type: {campaign_type}")  # Debug log
        
        python_exe = get_python_executable()
        temp_file = None
        
        if campaign_type == 'standard':
            selected_labels = data.get('selected_labels', [])
            if not selected_labels:
                return jsonify({'success': False, 'error': 'Geen labels geselecteerd'})
            
            # Create a temporary file with selected labels
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                for label in selected_labels:
                    # Clean the label and write without extra newline
                    clean_label = label.strip()
                    if clean_label:
                        f.write(clean_label + '\n')  # Use actual newline, not escaped
                temp_file = f.name
            
            print(f"Created temp file: {temp_file}")  # Debug log
            print(f"Temp file contents: {Path(temp_file).read_text()}")  # Debug log
            
            cmd = [
                python_exe, 'src/label_campaigns.py',
                '--customer', data.get('customer_id'),
                '--label-index', str(data.get('label_index', 0)),
                '--prefix', data.get('prefix', ''),
                '--daily-budget', str(data.get('daily_budget', 5.0)),
                '--labels-file', temp_file,
                '--pmax-type', data.get('pmax_type', 'feed-only'),
                '--apply', 'false'  # Preview mode
            ]
        elif campaign_type == 'pmax-all-labels':
            # For PMax ALL Labels, we automatically discover labels from last 30 days
            # No need for manual label selection - the script will discover all labels automatically
            cmd = [
                python_exe, 'src/label_campaigns.py',
                '--customer', data.get('customer_id'),
                '--label-index', str(data.get('label_index', 0)),
                '--prefix', data.get('prefix', 'PMax ALL'),
                '--daily-budget', str(data.get('daily_budget', 5.0)),
                '--pmax-type', data.get('pmax_type', 'feed-only'),
                '--apply', 'false'  # Preview mode
            ]
            
            # Add Merchant Center ID if specified (required for feed-only PMax)
            if data.get('merchant_id'):
                cmd.extend(['--merchant-id', data.get('merchant_id')])
            
            # Add ROAS factor if specified
            if data.get('roas_factor') and data.get('roas_factor') != 0:
                cmd.extend(['--roas-factor', str(data.get('roas_factor'))])
            
            # Add target languages and countries for PMax campaigns
            if data.get('target_languages'):
                cmd.extend(['--target-languages', data.get('target_languages')])
            
            if data.get('target_countries'):
                cmd.extend(['--target-countries', data.get('target_countries')])
            
            # Add feed-label for pmax-all-labels campaigns
            if data.get('feed_label'):
                cmd.extend(['--feed-label', data.get('feed_label')])
        elif campaign_type == 'product-type':
            # Route to Standard Shopping triplet creator
            cmd = [
                python_exe, 'src/create_product_type_campaigns.py',
                '--customer', data.get('customer_id'),
                '--prefix', data.get('prefix', 'Std Shopping'),
                '--daily-budget', str(data.get('daily_budget', 5.0)),
                '--apply', 'false'  # Preview mode
            ]
            
            # Add ROAS factor if specified
            if data.get('roas_factor') and data.get('roas_factor') != 0:
                cmd.extend(['--roas_factor', str(data.get('roas_factor'))])
            
            # Add start-enabled flag if checked
            if data.get('start_enabled'):
                cmd.append('--start-enabled')
            
            # Feed label
            if data.get('feed_label'):
                cmd.extend(['--feed-label', data.get('feed_label')])

            # Optional: max campaigns from UI
            if data.get('max_campaigns'):
                cmd.extend(['--max-campaigns', str(data.get('max_campaigns'))])
        
        # Add additional parameters for standard and product-type campaigns only
        if campaign_type in ['standard', 'product-type']:
            if data.get('target_languages'):
                cmd.extend(['--target-languages', data.get('target_languages')])
            
            if data.get('target_countries'):
                cmd.extend(['--target-countries', data.get('target_countries')])
            
            if data.get('feed_label'):
                cmd.extend(['--feed-label', data.get('feed_label')])
            
            if data.get('merchant_id'):
                cmd.extend(['--merchant-id', data.get('merchant_id')])
        
        print(f"Running command: {' '.join(cmd)}")  # Debug log
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)
        
        print(f"Return code: {result.returncode}")  # Debug log
        print(f"Stdout: {result.stdout[:500]}...")  # Debug log
        print(f"Stderr: {result.stderr[:500]}...")  # Debug log
        
        # Clean up temp file for standard campaigns
        if temp_file:
            try:
                os.unlink(temp_file)
            except:
                pass
        
        return jsonify({
            'success': result.returncode == 0,
            'output': result.stdout if result.returncode == 0 else result.stderr,
            'command': ' '.join(cmd)  # Return command for debugging
        })
    except Exception as e:
        print(f"Preview exception: {e}")  # Debug log
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/create-campaigns', methods=['POST'])
def create_campaigns():
    try:
        data = request.json
        campaign_type = data.get('campaign_type', 'standard')
        
        print(f"Create request - campaign_type: {campaign_type}")  # Debug log
        
        python_exe = get_python_executable()
        temp_file = None
        
        if campaign_type == 'standard':
            selected_labels = data.get('selected_labels', [])
            if not selected_labels:
                return jsonify({'success': False, 'error': 'Geen labels geselecteerd'})
            
            # Create a temporary file with selected labels
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                for label in selected_labels:
                    # Clean the label and write without extra newline
                    clean_label = label.strip()
                    if clean_label:
                        f.write(clean_label + '\n')  # Use actual newline, not escaped
                temp_file = f.name
            
            print(f"Created temp file: {temp_file}")  # Debug log
            print(f"Temp file contents: {Path(temp_file).read_text()}")  # Debug log
            
            cmd = [
                python_exe, 'src/label_campaigns.py',
                '--customer', data.get('customer_id'),
                '--label-index', str(data.get('label_index', 0)),
                '--prefix', data.get('prefix', ''),
                '--daily-budget', str(data.get('daily_budget', 5.0)),
                '--labels-file', temp_file,
                '--pmax-type', data.get('pmax_type', 'feed-only'),
                '--apply', 'true'
            ]
        elif campaign_type == 'pmax-all-labels':
            # For PMax ALL Labels, we automatically discover labels from last 30 days
            # No need for manual label selection - the script will discover all labels automatically
            cmd = [
                python_exe, 'src/label_campaigns.py',
                '--customer', data.get('customer_id'),
                '--label-index', str(data.get('label_index', 0)),
                '--prefix', data.get('prefix', 'PMax ALL'),
                '--daily-budget', str(data.get('daily_budget', 5.0)),
                '--pmax-type', data.get('pmax_type', 'feed-only'),
                '--apply', 'true'
            ]
            
            # Add Merchant Center ID if specified (required for feed-only PMax)
            if data.get('merchant_id'):
                cmd.extend(['--merchant-id', data.get('merchant_id')])
            
            # Add ROAS factor if specified
            if data.get('roas_factor') and data.get('roas_factor') != 0:
                cmd.extend(['--roas-factor', str(data.get('roas_factor'))])
            
            # Add start-enabled flag if checked
            if data.get('start_enabled'):
                cmd.append('--start-enabled')
            
            # Add target languages and countries for PMax campaigns
            if data.get('target_languages'):
                cmd.extend(['--target-languages', data.get('target_languages')])
            
            if data.get('target_countries'):
                cmd.extend(['--target-countries', data.get('target_countries')])
            
            # Add feed-label for pmax-all-labels campaigns
            if data.get('feed_label'):
                cmd.extend(['--feed-label', data.get('feed_label')])
        elif campaign_type == 'product-type':
            # Route to Standard Shopping triplet creator
            cmd = [
                python_exe, 'src/create_product_type_campaigns.py',
                '--customer', data.get('customer_id'),
                '--prefix', data.get('prefix', 'Std Shopping'),
                '--daily-budget', str(data.get('daily_budget', 5.0)),
                '--apply', 'true'
            ]
            
            # Add ROAS factor if specified
            if data.get('roas_factor') and data.get('roas_factor') != 0:
                cmd.extend(['--roas-factor', str(data.get('roas_factor'))])
            
            # Add start-enabled flag if checked
            if data.get('start_enabled'):
                cmd.append('--start-enabled')
            
            # Feed label
            if data.get('feed_label'):
                cmd.extend(['--feed-label', data.get('feed_label')])

            # Optional: max campaigns from UI
            if data.get('max_campaigns'):
                cmd.extend(['--max-campaigns', str(data.get('max_campaigns'))])
        
        # Add additional parameters for standard and product-type campaigns only
        if campaign_type in ['standard', 'product-type']:
            if data.get('target_languages'):
                cmd.extend(['--target-languages', data.get('target_languages')])
            
            if data.get('target_countries'):
                cmd.extend(['--target-countries', data.get('target_countries')])
            
            if data.get('feed_label'):
                cmd.extend(['--feed-label', data.get('feed_label')])
            
            if data.get('merchant_id'):
                cmd.extend(['--merchant-id', data.get('merchant_id')])
        
        print(f"Running command: {' '.join(cmd)}")  # Debug log
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)
        
        print(f"Return code: {result.returncode}")  # Debug log
        print(f"Stdout: {result.stdout[:500]}...")  # Debug log
        print(f"Stderr: {result.stderr[:500]}...")  # Debug log
        
        # Clean up temp file for standard campaigns
        if temp_file:
            try:
                os.unlink(temp_file)
            except:
                pass
        
        return jsonify({
            'success': result.returncode == 0,
            'output': result.stdout if result.returncode == 0 else result.stderr,
            'command': ' '.join(cmd)  # Return command for debugging
        })
    except Exception as e:
        print(f"Create exception: {e}")  # Debug log
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/weekly-monitor', methods=['POST'])
def weekly_monitor():
    try:
        data = request.json
        customer_id = data.get('customer_id')
        prefix = data.get('prefix', '')
        label_index = data.get('label_index', 0)
        min_impressions = data.get('min_impressions', 100)
        min_conversions = data.get('min_conversions', 0)
        auto_pause_empty = data.get('auto_pause_empty', False)
        apply_changes = data.get('apply_changes', False)
        detailed_report = data.get('detailed_report', False)
        export_csv = data.get('export_csv', False)
        include_roas = data.get('include_roas', True)
        include_ctr = data.get('include_ctr', True)
        include_budget = data.get('include_budget', True)
        include_volume = data.get('include_volume', True)
        include_labels = data.get('include_labels', True)
        include_trends = data.get('include_trends', True)
        
        print(f"Weekly monitor request for customer: {customer_id}")
        print(f"Performance metrics: ROAS={include_roas}, CTR={include_ctr}, Budget={include_budget}, Volume={include_volume}, Labels={include_labels}, Trends={include_trends}")
        
        python_exe = get_python_executable()
        # Run the weekly monitor script
        cmd = [
            python_exe, 'src/weekly_campaign_monitor.py',
            '--customer', customer_id,
            '--prefix', prefix,
            '--label-index', str(label_index),
            '--min-impressions', str(min_impressions),
            '--min-conversions', str(min_conversions),
            '--days-back', '30'
        ]
        
        if auto_pause_empty:
            cmd.append('--auto-pause-empty')
        
        if apply_changes:
            cmd.append('--apply')
        else:
            cmd.append('--dry-run')
        
        if detailed_report:
            cmd.append('--detailed-report')
        
        if export_csv:
            cmd.append('--export-csv')
        
        # Add performance metrics flags
        if include_roas:
            cmd.append('--include-roas')
        if include_ctr:
            cmd.append('--include-ctr')
        if include_budget:
            cmd.append('--include-budget')
        if include_volume:
            cmd.append('--include-volume')
        if include_labels:
            cmd.append('--include-labels')
        if include_trends:
            cmd.append('--include-trends')
        
        print(f"Running command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)
        
        print(f"Return code: {result.returncode}")
        print(f"Stdout: {result.stdout}")
        print(f"Stderr: {result.stderr}")
        
        return jsonify({
            'success': result.returncode == 0,
            'output': result.stdout if result.returncode == 0 else result.stderr,
            'command': ' '.join(cmd)
        })
        
    except Exception as e:
        print(f"Weekly monitor exception: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/sync-troas', methods=['POST'])
def sync_troas():
    """Manually sync campaign tROAS from current custom label 1 for a seller (label 0).

    Expected JSON body:
    {
      "customer_id": "747-204-9709",
      "seller": "uksoccershop",
      "days_back": 30,               # optional, default 30
      "target_roas_bps": 700,        # optional override; if omitted uses current label 1
      "dry_run": false               # optional, default false
    }
    """
    try:
        data = request.get_json() or {}
        customer_id = data.get('customer_id')
        seller = data.get('seller')
        days_back = int(data.get('days_back', 30))
        target_roas_bps = data.get('target_roas_bps')
        dry_run = bool(data.get('dry_run', False))

        if not customer_id:
            return jsonify({'success': False, 'error': 'customer_id is required'}), 400
        if not seller:
            return jsonify({'success': False, 'error': 'seller (custom label 0) is required'}), 400

        python_exe = get_python_executable()
        print(f"DEBUG: Detected Python executable: {python_exe}")
        cmd = [
            python_exe, 'src/sync_troas_from_label1.py',
            '--customer', customer_id,
            '--seller', seller,
            '--days-back', str(days_back)
        ]
        if target_roas_bps is not None:
            cmd.extend(['--target-roas-bps', str(target_roas_bps)])
        if dry_run:
            cmd.append('--dry-run')

        print(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)

        return jsonify({
            'success': result.returncode == 0,
            'output': result.stdout if result.returncode == 0 else result.stderr,
            'command': ' '.join(cmd)
        })
    except Exception as e:
        print(f"Sync tROAS exception: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/adjust-portfolio-roas', methods=['POST'])
def adjust_portfolio_roas():
    """Adjust tROAS for all portfolio TARGET_ROAS strategies with 'tROAS' in name."""
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        percentage = data.get('percentage')
        reset = data.get('reset', False)
        apply = data.get('apply', False)
        
        if not customer_id:
            return jsonify({'success': False, 'error': 'Customer ID is required'})
        
        if not reset and (percentage is None or percentage == 0):
            return jsonify({'success': False, 'error': 'Vul een percentage in (niet 0) of vink "Eerst resetten" aan (of beide).'})
        
        python_exe = get_python_executable()
        print(f"DEBUG: Detected Python executable: {python_exe}")
        # Build command: reset and/or percentage (both allowed: eerst reset, dan percentage)
        cmd = [
            python_exe,
            'src/adjust_portfolio_roas.py',
            '--customer', customer_id
        ]
        
        if reset:
            cmd.append('--reset')
        if percentage is not None:
            cmd.extend(['--percentage', str(percentage)])
        
        if apply:
            cmd.append('--apply')
        
        print(f"Running command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)
        
        print(f"Return code: {result.returncode}")
        print(f"Stdout: {result.stdout}")
        print(f"Stderr: {result.stderr}")
        
        return jsonify({
            'success': result.returncode == 0,
            'output': result.stdout if result.returncode == 0 else result.stderr,
            'command': ' '.join(cmd)
        })
        
    except Exception as e:
        print(f"Adjust portfolio ROAS exception: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/adjust-pmax-roas', methods=['POST'])
def adjust_pmax_roas():
    """Adjust tROAS for PMax campaigns with target_roas set directly in campaign."""
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        prefix = data.get('prefix')
        percentage = data.get('percentage')
        reset = data.get('reset', False)
        apply = data.get('apply', False)
        
        if not customer_id:
            return jsonify({'success': False, 'error': 'Customer ID is required'})
        
        if not reset and (percentage is None or percentage == 0):
            return jsonify({'success': False, 'error': 'Vul een percentage in (niet 0) of vink "Eerst resetten" aan (of beide).'})
        
        python_exe = get_python_executable()
        print(f"DEBUG: Detected Python executable: {python_exe}")
        # Build command: reset and/or percentage (both allowed: eerst reset, dan percentage)
        cmd = [
            python_exe,
            'src/adjust_pmax_roas.py',
            '--customer', customer_id
        ]
        
        if prefix:
            cmd.extend(['--prefix', prefix])
        if reset:
            cmd.append('--reset')
        if percentage is not None:
            cmd.extend(['--percentage', str(percentage)])
        
        if apply:
            cmd.append('--apply')
        
        print(f"Running command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)
        
        print(f"Return code: {result.returncode}")
        print(f"Stdout: {result.stdout}")
        print(f"Stderr: {result.stderr}")
        
        return jsonify({
            'success': result.returncode == 0,
            'output': result.stdout if result.returncode == 0 else result.stderr,
            'command': ' '.join(cmd)
        })
        
    except Exception as e:
        print(f"Adjust PMax ROAS exception: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/download-csv/<filename>')
def download_csv(filename):
    """Download CSV file."""
    try:
        # Security check - only allow CSV files
        if not filename.endswith('.csv'):
            return jsonify({'error': 'Invalid file type'}), 400
        
        file_path = Path(__file__).parent / filename
        if not file_path.exists():
            return jsonify({'error': 'File not found'}), 404
        
        return send_file(file_path, as_attachment=True, download_name=filename)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("[START] Starting Google Ads Tools Web Interface...")
    print("[URL] Open your browser and go to: http://localhost:8080")
    print("[STOP] Press Ctrl+C to stop the server")
    app.run(debug=True, host='0.0.0.0', port=8080)

