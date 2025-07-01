#!/usr/bin/env python3

import os
import sys
import json
import smtplib
import argparse
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

def get_env_var(var_name, default=None, required=False):
    """Get environment variable or return default value"""
    value = os.environ.get(var_name, default)
    if required and value is None:
        print(f"ERROR: Required environment variable {var_name} is not set.")
        sys.exit(1)
    return value

def load_vulnerability_data(file_path):
    """Load vulnerability data from JSON file"""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        hits = data.get('hits', {}).get('hits', [])
        total = data.get('hits', {}).get('total', {}).get('value', 0)
        
        return hits, total
    except Exception as e:
        print(f"ERROR: Failed to load data from file: {str(e)}")
        return [], 0

def analyze_issues(hits):
    """Analyze issue data and extract useful metrics"""
    severity_counts = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "info": 0,
    }
    
    app_codes = {}
    issue_types = set()
    high_severity_issues = []
    custodians = {}
    
    for hit in hits:
        source = hit.get('_source', {})
        severity = source.get('severity', '')
        
        # Handle null/empty severity - treat all issues as "medium" by default
        # or assign severity based on issue type
        if not severity or severity == 'null':
            # Assign severity based on issue type
            issue_type = source.get('issueType', '').lower()
            if 'vulnerability' in issue_type:
                severity = 'high'
            elif 'cryptography' in issue_type:
                severity = 'high'
            elif 'tss' in issue_type:
                severity = 'medium'
            elif 'av tss' in issue_type:
                severity = 'medium'
            elif 'open data' in issue_type:
                severity = 'low'
            else:
                severity = 'medium'  # default
        else:
            severity = severity.lower()
        
        app_code = source.get('appCode')
        issue_type = source.get('issueType')
        
        # Extract custodian information from contact-info structure
        contact_info = source.get('contact-info', {})
        custodian_name = contact_info.get('app_custodian_name', 'Unknown')
        custodian_email = contact_info.get('app_custodian_email', None)  # Future field
        
        # If no email in contact-info, try legacy field (fallback)
        if not custodian_email:
            custodian_email = source.get('custodian_email', None)
        
        if severity in severity_counts:
            severity_counts[severity] += 1
        
        app_code = source.get('appCode')
        if app_code:
            if app_code not in app_codes:
                app_codes[app_code] = {
                    'issue_types': set(),
                    'severity_counts': {
                        "critical": 0,
                        "high": 0,
                        "medium": 0,
                        "low": 0,
                        "info": 0,
                    }
                }
            
            if severity in app_codes[app_code]['severity_counts']:
                app_codes[app_code]['severity_counts'][severity] += 1
            
            issue_type = source.get('issueType')
            if issue_type:
                app_codes[app_code]['issue_types'].add(issue_type)
                issue_types.add(issue_type)
            
            # Track custodians - use email if available, otherwise use name or default
            custodian_key = custodian_email if custodian_email else f"no-email-{custodian_name}"
            if custodian_key not in custodians:
                custodians[custodian_key] = {
                    'app_codes': set(),
                    'issues': [],
                    'custodian_name': custodian_name,
                    'has_email': bool(custodian_email)
                }
            custodians[custodian_key]['app_codes'].add(app_code)
            custodians[custodian_key]['issues'].append(source)
        
        if severity in ['critical', 'high']:
            high_severity_issues.append({
                'type': source.get('issueType', 'Unknown'),
                'severity': severity.upper(),
                'component': f"{source.get('affectedItemType', 'Unknown')} - {source.get('affectedItemName', 'Unknown')}",
                'app_code': app_code,
                'remediation_link': source.get('remediationLink', source.get('solution', 'N/A'))
            })
    
    app_codes_list = [
        {
            'app_code': code,
            'issue_types': list(details['issue_types']),
            'severity_counts': details['severity_counts']
        }
        for code, details in app_codes.items()
    ]
    
    return {
        "severity_counts": severity_counts,
        "app_codes": app_codes_list,
        "issue_types": list(issue_types),
        "high_severity_count": severity_counts["critical"] + severity_counts["high"],
        "high_severity_issues": high_severity_issues,
        "custodian": custodians
    }

def identify_non_compliant_apps(hits):
    """Identify non-compliant apps based on severity thresholds"""
    app_compliance = {}
    
    # Define compliance thresholds
    thresholds = {
        "critical": 0,  # Any critical finding makes an app non-compliant
        "high": 0,      # Any high findings make an app non-compliant
    }
    
    # Group findings by appcode
    for hit in hits:
        source = hit.get('_source', {})
        app_code = source.get('appCode')
        severity = source.get('severity', '')
        
        # Handle null/empty severity - assign based on issue type
        if not severity or severity == 'null':
            issue_type = source.get('issueType', '').lower()
            if 'vulnerability' in issue_type:
                severity = 'high'
            elif 'cryptography' in issue_type:
                severity = 'high'
            elif 'tss' in issue_type:
                severity = 'medium'
            elif 'av tss' in issue_type:
                severity = 'medium'
            elif 'open data' in issue_type:
                severity = 'low'
            else:
                severity = 'medium'  # default
        else:
            severity = severity.lower()
        
        if not app_code:
            continue
        
        if app_code not in app_compliance:
            app_compliance[app_code] = {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "info": 0,
                "is_compliant": True,
                "reasons": []
            }
        
        if severity in app_compliance[app_code]:
            app_compliance[app_code][severity] += 1
    
    # Check compliance for each appcode
    for app_code, data in app_compliance.items():
        if data["critical"] > thresholds["critical"]:
            data["is_compliant"] = False
            data["reasons"].append(f"Has {data['critical']} critical findings (threshold: {thresholds['critical']})")
        
        if data["high"] > thresholds["high"]:
            data["is_compliant"] = False
            data["reasons"].append(f"Has {data['high']} high findings (threshold: {thresholds['high']})")
        
        if data["medium"] > thresholds["medium"]:
            data["is_compliant"] = False
            data["reasons"].append(f"Has {data['medium']} medium findings (threshold: {thresholds['medium']})")
    
    return app_compliance

def generate_report(input_file, output_file):
    """Generate a formatted report from data"""
    hits, total = load_vulnerability_data(input_file)
    
    if total == 0:
        print("No issues found.")
        return False
    
    analysis = analyze_issues(hits)
    
    compliance_status = identify_non_compliant_apps(hits)
    
    # Get date range from environment variables or use defaults
    end_date = os.environ.get('END_DATE', datetime.now().strftime("%Y-%m-%d"))
    start_date = os.environ.get('START_DATE', (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d"))
    
    report = {
        "summary": {
            "total_issues": total,
            "high_severity_count": analysis["high_severity_count"],
            "app_codes": analysis["app_codes"],
            "issue_types": analysis["issue_types"],
            "generated_at": datetime.now().strftime("%Y-%m-%d"),
            "start_date": start_date,
            "end_date": end_date,
            "high_severity_issues": analysis["high_severity_issues"],
            "non_compliant_apps": [
                {
                    "app_code": app_code,
                    "reasons": data["reasons"],
                    "severity_counts": {
                        "critical": data["critical"],
                        "high": data["high"],
                        "medium": data["medium"],
                        "low": data["low"],
                        "info": data["info"]
                    }
                }
                for app_code, data in compliance_status.items()
                if not data["is_compliant"]
            ]
        },
        "severity_breakdown": analysis["severity_counts"],
        "issue_types": analysis["issue_types"],
        "compliance_details": compliance_status,
        "raw_data": hits[:10]
    }
    
    try:
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"Report generated and saved to {output_file}")
        return True
    except Exception as e:
        print(f"ERROR: Failed to generate report: {str(e)}")
        return False

def prepare_email_content(template_file, report_data):
    """Prepare email content using template and report data"""
    try:
        
        with open(template_file, 'r') as f:
            template = f.read()
        
        with open(report_data, 'r') as f:
            data = json.load(f)
        
        report_date = data["summary"]["generated_at"]
        app_code = ", ".join([app['app_code'] for app in data["summary"]["app_codes"]]) if data["summary"]["app_codes"] else "Unknown"
        total_issues = data["summary"]["total_issues"]
        high_severity_count = data["summary"]["high_severity_count"]
        start_date = data["summary"]["start_date"]
        end_date = data["summary"]["end_date"]
        high_severity_issues = data["summary"]["high_severity_issues"]
        non_compliant_apps = data["summary"].get("non_compliant_apps", [])
        
        severity_counts = data["severity_breakdown"]
        critical_count = severity_counts.get("critical", 0)
        high_count = severity_counts.get("high", 0)
        medium_count = severity_counts.get("medium", 0)
        low_count = severity_counts.get("low", 0)
        info_count = severity_counts.get("info", 0)
        
        issue_types = ", ".join(data["summary"]["issue_types"]) if "issue_types" in data["summary"] else ""
        
        content = template
        
        # Replace basic variables
        content = content.replace("{{ report_date }}", report_date)
        content = content.replace("{{ app_code }}", app_code)
        content = content.replace("{{ total_issues }}", str(total_issues))
        content = content.replace("{{ high_severity_count }}", str(high_severity_count))
        content = content.replace("{{ start_date }}", start_date)
        content = content.replace("{{ end_date }}", end_date)
        content = content.replace("{{ issue_types }}", issue_types)
        content = content.replace("{{ critical_count }}", str(critical_count))
        content = content.replace("{{ high_count }}", str(high_count))
        content = content.replace("{{ medium_count }}", str(medium_count))
        content = content.replace("{{ low_count }}", str(low_count))
        content = content.replace("{{ info_count }}", str(info_count))
        content = content.replace("{{ generated_at }}", report_date)
        
        # Process high severity issues table
        if high_severity_issues:
            table_rows = []
            for issue in high_severity_issues:
                remediation_link = issue.get('remediation_link', 'N/A')
                app_code_val = issue.get('app_code', 'N/A')
                component = issue.get('component', 'Unknown')
                issue_type = issue.get('type', 'Unknown')
                severity = issue.get('severity', 'Unknown')
                
                table_row = f"| {issue_type} | {severity} | {component} | {app_code_val} | {remediation_link} |"
                table_rows.append(table_row)
            
            # Replace the template loop with actual table rows
            loop_pattern = "{% for issue in high_severity_issues %}\n| {{ issue.type }} | {{ issue.severity }} | {{ issue.component }} | {{ issue.app_code | default('N/A') }} | {{ issue.remediation_link | default('N/A') }} |\n{% endfor %}"
            table_content = "\n".join(table_rows)
            content = content.replace(loop_pattern, table_content)
        else:
            # Remove the entire table section if no high severity issues
            start_marker = "{% for issue in high_severity_issues %}"
            end_marker = "{% endfor %}"
            start_pos = content.find(start_marker)
            end_pos = content.find(end_marker)
            if start_pos != -1 and end_pos != -1:
                content = content[:start_pos] + "No high severity issues found." + content[end_pos + len(end_marker):]
        
        # Process non-compliant apps section
        if non_compliant_apps:
            # Keep the non-compliant apps section
            content = content.replace("{% if non_compliant_apps %}", "")
            content = content.replace("{% endif %}", "")
            
            # Process reasons loop
            if non_compliant_apps:
                reasons = non_compliant_apps[0]["reasons"]
                reasons_text = "\n".join([f"- {reason}" for reason in reasons])
                
                # Replace the reasons loop
                reasons_pattern = "{% for reason in non_compliant_apps[0].reasons %}\n- {{ reason }}\n{% endfor %}"
                content = content.replace(reasons_pattern, reasons_text)
                
                # Replace severity counts for non-compliant apps
                severity_counts_nc = non_compliant_apps[0]["severity_counts"]
                content = content.replace("{{ non_compliant_apps[0].severity_counts.critical }}", str(severity_counts_nc.get("critical", 0)))
                content = content.replace("{{ non_compliant_apps[0].severity_counts.high }}", str(severity_counts_nc.get("high", 0)))
                content = content.replace("{{ non_compliant_apps[0].severity_counts.medium }}", str(severity_counts_nc.get("medium", 0)))
                content = content.replace("{{ non_compliant_apps[0].severity_counts.low }}", str(severity_counts_nc.get("low", 0)))
                content = content.replace("{{ non_compliant_apps[0].severity_counts.info }}", str(severity_counts_nc.get("info", 0)))
        else:
            # Remove the entire non-compliant apps section
            start_marker = "{% if non_compliant_apps %}"
            end_marker = "{% endif %}"
            start_pos = content.find(start_marker)
            end_pos = content.find(end_marker)
            if start_pos != -1 and end_pos != -1:
                content = content[:start_pos] + content[end_pos + len(end_marker):]
        
        return content
    except Exception as e:
        print(f"ERROR: Failed to prepare email content: {str(e)}")
        return None

def main():
    """Main function to process data"""
    parser = argparse.ArgumentParser(description='Process data from Elasticsearch')
    parser.add_argument('--input', required=True, help='Input JSON file with data')
    parser.add_argument('--output', required=True, help='Output file for the processed report')
    parser.add_argument('--email-template', help='Email template file for notifications')
    parser.add_argument('--email-output', help='Output file for the email content')
    
    args = parser.parse_args()
    
    success = generate_report(args.input, args.output)
    
    if success and args.email_template and args.email_output:
        email_content = prepare_email_content(args.email_template, args.output)
        if email_content:
            try:
                with open(args.email_output, 'w') as f:
                    f.write(email_content)
                print(f"Email content generated and saved to {args.email_output}")
            except Exception as e:
                print(f"ERROR: Failed to save email content: {str(e)}")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main()) 
