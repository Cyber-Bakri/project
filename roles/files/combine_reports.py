#!/usr/bin/env python3

import json
import sys
from pathlib import Path

def combine_reports(output_dir):
    """Combine all processed reports into a single file for notifications"""
    
    output_path = Path(output_dir)
    combined_data = {
        'custodian': {}, 
        'summary': {'app_codes': []}
    }
    reports_processed = 0
    
    # Find all processed report files
    for report_file in output_path.glob('*_report_processed.json'):
        if report_file.exists():
            try:
                with open(report_file) as f:
                    data = json.load(f)
                    reports_processed += 1
                    
                    # Merge custodian data (skip empty ones)
                    if 'custodian' in data and data['custodian']:
                        combined_data['custodian'].update(data['custodian'])
                    
                    # Merge app codes (skip empty ones)
                    if ('summary' in data and 
                        'app_codes' in data['summary'] and 
                        data['summary']['app_codes']):
                        combined_data['summary']['app_codes'].extend(
                            data['summary']['app_codes'])
                            
            except Exception as e:
                print(f'Warning: Could not process {report_file}: {e}')
    
    # Save combined report (even if empty)
    combined_file = output_path / 'combined_report_processed.json'
    with open(combined_file, 'w') as f:
        json.dump(combined_data, f, indent=2)
    
    print(f'Combined {reports_processed} reports successfully')
    print(f'Total custodians: {len(combined_data["custodian"])}')
    print(f'Total app codes: {len(combined_data["summary"]["app_codes"])}')
    
    return True

if __name__ == "__main__":
    output_dir = sys.argv[1] if len(sys.argv) > 1 else 'roles/files/output'
    success = combine_reports(output_dir)
    sys.exit(0 if success else 1) 