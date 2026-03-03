from flask import Flask, render_template, request, jsonify, flash, redirect, url_for
import os
import sys
from pathlib import Path
import subprocess
import json
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change this!

# Add the src directory to Python path
sys.path.append(str(Path(__file__).parent / 'src'))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin/adwords-tools')
def adwords_tools():
    return render_template('adwords_tools.html')

@app.route('/api/discover-labels', methods=['POST'])
def discover_labels():
    try:
        data = request.json
        customer_id = data.get('customer_id')
        label_index = data.get('label_index', 0)
        sales_country = data.get('sales_country', 'DK')
        merchant_id = data.get('merchant_id')
        
        # Run the label discovery
        cmd = [
            'py', 'src/label_campaigns.py',
            '--customer', customer_id,
            '--label-index', str(label_index),
            '--target-countries', sales_country,
            '--apply', 'false'
        ]
        
        if merchant_id:
            cmd.extend(['--merchant-id', merchant_id])
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'output': result.stdout,
                'labels': parse_labels_from_output(result.stdout)
            })
        else:
            return jsonify({
                'success': False,
                'error': result.stderr
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/create-campaigns', methods=['POST'])
def create_campaigns():
    try:
        data = request.json
        customer_id = data.get('customer_id')
        label_index = data.get('label_index', 0)
        sales_country = data.get('sales_country', 'DK')
        merchant_id = data.get('merchant_id')
        prefix = data.get('prefix', 'PMax Feed')
        daily_budget = data.get('daily_budget', 5.0)
        target_roas = data.get('target_roas')
        eu_political = data.get('eu_political', 'false')
        
        # Run the campaign creation
        cmd = [
            'py', 'src/label_campaigns.py',
            '--customer', customer_id,
            '--label-index', str(label_index),
            '--target-countries', sales_country,
            '--prefix', prefix,
            '--daily-budget', str(daily_budget),
            '--eu-political', eu_political,
            '--apply', 'true'
        ]
        
        if merchant_id:
            cmd.extend(['--merchant-id', merchant_id])
        
        if target_roas:
            cmd.extend(['--target-roas', str(target_roas)])
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'output': result.stdout,
                'campaigns_created': parse_campaigns_from_output(result.stdout)
            })
        else:
            return jsonify({
                'success': False,
                'error': result.stderr
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

def parse_labels_from_output(output):
    """Parse discovered labels from the script output"""
    labels = []
    lines = output.split('\n')
    for line in lines:
        if "impressions" in line and "'" in line:
            # Parse lines like: 'uksoccershop': 12650 impressions
            try:
                parts = line.split("':")
                if len(parts) == 2:
                    label = parts[0].strip().strip("'")
                    impressions = parts[1].split()[0]
                    labels.append({
                        'label': label,
                        'impressions': int(impressions)
                    })
            except:
                continue
    return labels

def parse_campaigns_from_output(output):
    """Parse created campaigns from the script output"""
    campaigns = []
    lines = output.split('\n')
    for line in lines:
        if "Campaign aangemaakt:" in line:
            try:
                campaign_id = line.split("customers/")[1].split("/campaigns/")[1].strip()
                campaigns.append(campaign_id)
            except:
                continue
    return campaigns

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
